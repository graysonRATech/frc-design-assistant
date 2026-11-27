"""Chat Lambda: retrieve from the Knowledge Base, answer with Claude, cite, log, and meter spend.

Invoked two ways, both returning an API Gateway-style response:
- HTTP API with a JWT authorizer: the user comes from the verified token claims. Besides
  POST /chat, it serves the saved-chat routes (list, open, rename, delete, stop).
- Direct `lambda:InvokeFunction` (the `kb ask` CLI): the caller already holds IAM rights to the
  function, so the `user` field in the payload is trusted. With `"stream": true` the answer goes
  through the streaming pipeline instead (streaming.py, as the web page and Slack use it): the
  post-deploy smoke test and the daily check use this, so they exercise the same Bedrock calls
  and permissions students depend on.

The web page streams answers from a separate function (server.py) that shares the helpers here.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache

from .conversations import ChatNotFound, Conversations
from . import review
from .prompt import SYSTEM_PROMPT, build_user_message, cited_sources, sources_from_retrieval
from .usage import LimitExceeded, Limits, Pricing, UsageLedger

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

MAX_QUESTION_CHARS = 2000
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 4000


@dataclass(frozen=True)
class Settings:
    knowledge_base_id: str
    table_name: str
    model_id: str
    endpoint: str  # "mantle" (Claude in Amazon Bedrock) or "runtime" (InvokeModel)
    max_tokens: int
    effort: str  # empty for models without the effort parameter (e.g. Haiku 4.5)
    top_k: int
    limits: Limits
    pricing: Pricing
    audit_retention_days: int
    chat_retention_days: int = 90

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            knowledge_base_id=env["KNOWLEDGE_BASE_ID"],
            table_name=env["TABLE_NAME"],
            model_id=env.get("MODEL_ID", "anthropic.claude-sonnet-5-5"),
            endpoint=env.get("CLAUDE_ENDPOINT", "mantle"),
            max_tokens=int(env.get("MAX_TOKENS", "1500")),
            effort=env.get("EFFORT", "low"),
            top_k=int(env.get("TOP_K", "6")),
            limits=Limits(float(env.get("USER_DAILY_LIMIT_USD", "0.50")), float(env.get("MONTHLY_LIMIT_USD", "20"))),
            pricing=Pricing(float(env.get("PRICE_INPUT_PER_MTOK", "2")), float(env.get("PRICE_OUTPUT_PER_MTOK", "10"))),
            audit_retention_days=int(env.get("AUDIT_RETENTION_DAYS", "365")),
            chat_retention_days=int(env.get("CHAT_RETENTION_DAYS", "90")),
        )


@dataclass
class Dependencies:
    settings: Settings
    agent_runtime: object  # boto3 bedrock-agent-runtime client
    claude: object  # anthropic.AnthropicBedrockMantle or anthropic.AnthropicBedrock
    table: object  # boto3 DynamoDB Table


@cache
def _default_dependencies(claude_timeout: float = 24.0) -> Dependencies:
    import boto3
    from anthropic import AnthropicBedrock, AnthropicBedrockMantle

    settings = Settings.from_env()
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = AnthropicBedrockMantle if settings.endpoint == "mantle" else AnthropicBedrock
    return Dependencies(
        settings=settings,
        agent_runtime=boto3.client("bedrock-agent-runtime", region_name=region),
        # API Gateway gives up at 29 s, so one bounded attempt plus one quick retry on throttling.
        # The streaming function has no such ceiling and passes a longer timeout.
        claude=client(aws_region=region, timeout=claude_timeout, max_retries=1),
        table=boto3.resource("dynamodb", region_name=region).Table(settings.table_name),
    )


ALLOWED_GROUPS = {"student", "mentor", "admin"}
REVIEWER_GROUPS = {"mentor", "admin"}
FEEDBACK_RATINGS = ("up", "down")
MAX_FEEDBACK_CHARS = 1000


def lambda_handler(event, context, deps: Dependencies | None = None):
    deps = deps or _default_dependencies()
    request_id = getattr(context, "aws_request_id", None) or str(uuid.uuid4())
    try:
        user_id, groups = _identity(event)
        if not user_id:
            return _response(401, {"error": "Unauthenticated"})
        if not ALLOWED_GROUPS.intersection(groups):
            return _response(403, {"error": "Your account doesn't have access. Ask a mentor."})
        route = event.get("routeKey", "")
        if route == "POST /feedback":
            return _feedback(deps, user_id, _json_body(event))
        if route in REVIEW_ROUTES:
            if not REVIEWER_GROUPS.intersection(groups):
                return _response(403, {"error": "Only mentors can review feedback."})
            return _review(deps, route, user_id, event)
        if route in CHAT_ROUTES:
            return _chats(deps, route, user_id, event)
        if route in SETTINGS_ROUTES:
            return _settings(deps, route, user_id, event)
        payload = _payload(event)
    except ValueError as error:
        return _response(400, {"error": str(error)})
    if event.get("stream") is True and "requestContext" not in event:
        return _streamed_check(deps, request_id, user_id, groups, payload)
    return _answer(deps, request_id, user_id, groups, payload)


def _streamed_check(deps: Dependencies, request_id: str, user_id: str, groups: list[str], payload: dict):
    """One question through the streaming pipeline, collected into a single response.

    Failures are logged at ERROR, which the answer-errors alarm counts. The chat it creates is
    deleted afterwards, so repeated checks don't pile up saved chats.
    """
    from .streaming import Rejected, prepare, run

    prepared = prepare(deps, request_id, user_id, groups, {"question": payload["question"]})
    if isinstance(prepared, Rejected):
        return _response(prepared.status, {"error": prepared.error, **prepared.extra})
    events = []
    try:
        run(prepared, events.append, lambda: False)
    finally:
        prepared.chats.delete(user_id, prepared.chat["id"])
    answer = ""
    for event in events:
        if event["type"] == "delta":
            answer += event["text"]
        elif event["type"] == "replace":
            answer = event["text"]
    last = events[-1] if events else {"type": "error", "error": "no events"}
    if last["type"] == "error":
        return _response(502, {"error": last["error"]})
    if not prepared.sources:
        log.error("Check question retrieved no sources; is the Knowledge Base empty?")
        return _response(502, {"error": "No sources retrieved", "answer": answer})
    return _response(
        200, {"answer": answer.strip(), "sources": last["sources"], "request_id": request_id, "usage": last["usage"]}
    )


CHAT_ROUTES = ("GET /chats", "GET /chats/{id}", "PATCH /chats/{id}", "DELETE /chats/{id}", "POST /chats/stop")


def _chats(deps: Dependencies, route: str, user_id: str, event: dict):
    chats = Conversations(deps.table, deps.settings.chat_retention_days)
    chat_id = (event.get("pathParameters") or {}).get("id", "")
    try:
        if route == "GET /chats":
            return _response(200, {"chats": chats.list(user_id)})
        if route == "GET /chats/{id}":
            return _response(200, chats.get(user_id, chat_id))
        if route == "DELETE /chats/{id}":
            chats.delete(user_id, chat_id)
            return _response(200, {"ok": True})
        body = _json_body(event)
        if route == "PATCH /chats/{id}":
            if not isinstance(body.get("title"), str):
                raise ValueError("'title' is required")
            return _response(200, {"title": chats.rename(user_id, chat_id, body["title"])})
        if not isinstance(body.get("request_id"), str) or not body["request_id"]:
            raise ValueError("'request_id' is required")
        chats.request_stop(user_id, body["request_id"], datetime.now(UTC))
        return _response(200, {"ok": True})
    except ChatNotFound:
        return _response(404, {"error": "That chat doesn't exist, or it was deleted."})


SETTINGS_ROUTES = ("GET /settings", "PUT /settings")
THEMES = ("auto", "forge", "collegiate", "blueprint")


def _settings(deps: Dependencies, route: str, user_id: str, event: dict):
    """Per-user preferences (just the theme for now), kept so they follow the student across devices."""
    key = {"pk": f"SETTINGS#{user_id}", "sk": "profile"}
    if route == "GET /settings":
        item = deps.table.get_item(Key=key).get("Item") or {}
        return _response(200, {"theme": item.get("theme", "auto")})
    theme = _json_body(event).get("theme")
    if theme not in THEMES:
        raise ValueError(f"'theme' must be one of {', '.join(THEMES)}")
    deps.table.put_item(Item={**key, "theme": theme, "updated_at": datetime.now(UTC).isoformat(timespec="seconds")})
    return _response(200, {"theme": theme})


def limit_message(scope: str) -> str:
    if scope == "daily":
        return "You've reached today's question limit. It resets at midnight UTC."
    return "The team's monthly assistant budget is used up. Let a mentor know."


def retrieve_sources(deps: Dependencies, question: str):
    retrieved = deps.agent_runtime.retrieve(
        knowledgeBaseId=deps.settings.knowledge_base_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": deps.settings.top_k}},
    )["retrievalResults"]
    return sources_from_retrieval(retrieved)


def claude_request(settings: Settings, history: list[dict], question: str, sources) -> dict:
    options = {"output_config": {"effort": settings.effort}} if settings.effort else {}
    return {
        "model": settings.model_id,
        "max_tokens": settings.max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [*history, {"role": "user", "content": build_user_message(question, sources)}],
        **options,
    }


REFUSAL_ANSWER = "I can't help with that one. Try rephrasing, or ask a mentor."
CUT_OFF_NOTE = "\n\n*(Answer cut off at the length limit. Ask a narrower follow-up for the rest.)*"


def _feedback(deps: Dependencies, user_id: str, body: dict):
    rating, target = body.get("rating"), body.get("request_id")
    if rating not in FEEDBACK_RATINGS or not isinstance(target, str) or not target:
        raise ValueError("'request_id' and 'rating' ('up' or 'down') are required")
    comment = body.get("comment") or ""
    if not isinstance(comment, str):
        raise ValueError("'comment' must be a string")
    now = datetime.now(UTC)
    rated = review.find_answer(deps.table, user_id, target[:64], now, deps.settings.chat_retention_days)
    deps.table.put_item(
        Item={
            **review.answer_fields(rated),
            "pk": "FEEDBACK",
            "sk": f"{now.isoformat(timespec='milliseconds')}#{target[:64]}",
            "request_id": target[:64],
            "user": user_id,
            "rating": rating,
            "comment": comment[:MAX_FEEDBACK_CHARS],
            "expires_at": int((now + timedelta(days=deps.settings.audit_retention_days)).timestamp()),
        }
    )
    return _response(200, {"ok": True})


REVIEW_ROUTES = ("GET /review", "POST /review")


def _review(deps: Dependencies, route: str, user_id: str, event: dict):
    """Mentor-only: list rated answers, and mark one reviewed."""
    if route == "GET /review":
        params = event.get("queryStringParameters") or {}
        return _response(
            200,
            review.list_feedback(
                deps.table,
                rating=params.get("rating", "down"),
                status=params.get("status", "open"),
                window_days=deps.settings.chat_retention_days,
                cursor=params.get("cursor") or None,
            ),
        )
    body = _json_body(event)
    try:
        marked = review.mark(deps.table, body.get("id"), body.get("status"), body.get("note") or "", user_id, datetime.now(UTC))
    except LookupError:
        return _response(404, {"error": "That feedback doesn't exist any more."})
    return _response(200, marked)


def _answer(deps: Dependencies, request_id: str, user_id: str, groups: list[str], payload: dict):
    settings = deps.settings
    question = payload["question"]
    now = datetime.now(UTC)
    ledger = UsageLedger(deps.table, settings.limits, settings.pricing)
    try:
        ledger.check(user_id, now)
    except LimitExceeded as error:
        audit(deps, request_id, user_id, now, question, outcome=f"limit:{error.scope}")
        return _response(429, {"error": limit_message(error.scope), "limit": error.scope})

    started = time.monotonic()
    sources = retrieve_sources(deps, question)
    message = deps.claude.messages.create(**claude_request(settings, payload["history"], question, sources))
    answer = "".join(block.text for block in message.content if block.type == "text").strip()
    if message.stop_reason == "refusal":
        answer = REFUSAL_ANSWER
    elif message.stop_reason == "max_tokens":
        answer += CUT_OFF_NOTE

    usage = message.usage
    cost = ledger.charge(user_id, now, usage.input_tokens, usage.output_tokens)
    cited = cited_sources(answer, sources)
    audit(
        deps,
        request_id,
        user_id,
        now,
        question,
        outcome=message.stop_reason or "unknown",
        groups=groups,
        answer=answer,
        retrieved=[{"url": s.url, "score": s.score} for s in sources],
        cited=[s.url for s in cited],
        sources=[{"number": s.number, "title": s.title, "url": s.url} for s in cited],
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        micro_usd=cost,
        latency_ms=round((time.monotonic() - started) * 1000),
        model=settings.model_id,
    )
    return _response(
        200,
        {
            "answer": answer,
            "sources": [{"number": s.number, "title": s.title, "url": s.url} for s in cited],
            "request_id": request_id,
            "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cost_usd": cost / 1e6},
        },
    )


def _identity(event: dict) -> tuple[str | None, list[str]]:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims")
    if claims is not None:
        groups = claims.get("cognito:groups", "")
        # HTTP API flattens list claims to "[a b]" strings.
        groups = groups.strip("[]").split() if isinstance(groups, str) else list(groups)
        return claims.get("email") or claims.get("sub"), groups
    if "requestContext" in event:
        return None, []
    user = event.get("user")
    if not isinstance(user, str) or not user.strip():
        raise ValueError("Direct invocations must include a 'user' string")
    return f"cli:{user.strip()}", ["admin"]


def _json_body(event: dict) -> dict:
    body = event.get("body", event)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as error:
            raise ValueError("Body must be JSON") from error
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")
    return body


def _payload(event: dict) -> dict:
    body = _json_body(event)
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("'question' is required")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"'question' must be at most {MAX_QUESTION_CHARS} characters")
    return {"question": question.strip(), "history": history_for_claude(body.get("history"))}


def history_for_claude(raw) -> list[dict]:
    """Keep the most recent well-formed user/assistant pairs; drop anything else."""
    if not isinstance(raw, list):
        return []
    messages = [
        {"role": m["role"], "content": m["content"][:MAX_HISTORY_CHARS]}
        for m in raw
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()
    ]
    pairs = [
        messages[i : i + 2]
        for i in range(0, len(messages) - 1)
        if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant"
    ]
    return [m for pair in pairs[-(MAX_HISTORY_MESSAGES // 2) :] for m in pair]


def audit(deps: Dependencies, request_id: str, user_id: str, now: datetime, question: str, **fields):
    expires = now + timedelta(days=deps.settings.audit_retention_days)
    item = {
        "pk": f"AUDIT#{user_id}",
        "sk": f"{now.isoformat(timespec='milliseconds')}#{request_id}",
        "request_id": request_id,
        "user": user_id,
        "question": question,
        "expires_at": int(expires.timestamp()),
        **fields,
    }
    deps.table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body, default=str)}
