"""One streamed answer inside a saved chat: checks and retrieval first, then Claude's text as it
arrives, then save, meter and audit. Transport-free: server.py turns events into NDJSON lines.

Events sent to the browser, one JSON object per line:
    {"type": "start", "chat_id", "request_id", "sources"}   sources: everything retrieved
    {"type": "delta", "text"}                    more answer text
    {"type": "replace", "text"}                  the whole answer changed (refusal)
    {"type": "done", "chat_id", "title", "sources", "request_id", "stopped", "saved", "usage"}
                                                 sources: only those the answer cites
    {"type": "error", "error"}
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .conversations import MAX_TURNS, ChatFull, ChatNotFound, Conversations, new_chat_id, title_from
from .handler import (
    CUT_OFF_NOTE,
    MAX_QUESTION_CHARS,
    REFUSAL_ANSWER,
    Dependencies,
    audit,
    claude_request,
    history_for_claude,
    limit_message,
    retrieve_sources,
)
from .prompt import cited_sources
from .usage import LimitExceeded, UsageLedger

log = logging.getLogger(__name__)
STOP_POLL_SECONDS = 1.0


class Disconnected(Exception):
    """The browser went away mid-answer."""


@dataclass
class Rejected:
    status: int
    error: str
    extra: dict = field(default_factory=dict)


@dataclass
class Prepared:
    deps: Dependencies
    chats: Conversations
    request_id: str
    user_id: str
    groups: list[str]
    now: datetime
    chat: dict
    question: str
    sources: list
    history: list[dict]


def prepare(
    deps: Dependencies, request_id: str, user_id: str, groups: list[str], body: dict, chats=None
) -> Prepared | Rejected:
    """Everything that can fail with a plain JSON error, before any answer text is sent.

    `chats` stores the conversation: the student's saved chats by default, or a Slack thread
    (slack.ThreadStore), which has the same get/save methods.
    """
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        return Rejected(400, "'question' is required")
    if len(question) > MAX_QUESTION_CHARS:
        return Rejected(400, f"'question' must be at most {MAX_QUESTION_CHARS} characters")
    question = question.strip()
    now = datetime.now(UTC)
    chats = chats or Conversations(deps.table, deps.settings.chat_retention_days)

    if body.get("chat_id"):
        try:
            chat = chats.get(user_id, body["chat_id"])
        except ChatNotFound:
            return Rejected(404, "That chat doesn't exist, or it was deleted.")
    else:
        chat = {"id": new_chat_id(now), "title": title_from(question), "messages": []}

    messages = chat["messages"]
    if body.get("replace_last"):  # retry, or an edited last question: drop the last turn first
        if messages and messages[-1]["role"] == "assistant":
            messages.pop()
        if messages and messages[-1]["role"] == "user":
            messages.pop()
    if len(messages) // 2 >= MAX_TURNS:
        return Rejected(409, "This chat is full. Start a new chat to keep going.")

    ledger = UsageLedger(deps.table, deps.settings.limits, deps.settings.pricing)
    try:
        ledger.check(user_id, now)
    except LimitExceeded as error:
        audit(deps, request_id, user_id, now, question, outcome=f"limit:{error.scope}")
        return Rejected(429, limit_message(error.scope), {"limit": error.scope})

    sources = retrieve_sources(deps, question)
    history = history_for_claude([{"role": m["role"], "content": m["content"]} for m in messages])
    return Prepared(deps, chats, request_id, user_id, groups, now, chat, question, sources, history)


def run(p: Prepared, emit, should_stop) -> None:
    """Stream the answer through `emit(event)`; `should_stop()` reports a stop request."""
    settings = p.deps.settings
    started = time.monotonic()
    connected = True

    def send(event: dict) -> None:
        nonlocal connected
        if connected:
            try:
                emit(event)
            except Disconnected:
                connected = False

    # All retrieved sources up front, so [n] citations can link while the text streams in.
    retrieved = [{"number": s.number, "title": s.title, "url": s.url} for s in p.sources]
    send({"type": "start", "chat_id": p.chat["id"], "request_id": p.request_id, "sources": retrieved})
    parts, stopped, stop_reason = [], False, "unknown"
    input_tokens = output_tokens = 0
    try:
        with p.deps.claude.messages.stream(**claude_request(settings, p.history, p.question, p.sources)) as stream:
            next_poll = time.monotonic() + STOP_POLL_SECONDS
            for text in stream.text_stream:
                parts.append(text)
                send({"type": "delta", "text": text})
                if not connected:
                    stopped = True
                elif time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + STOP_POLL_SECONDS
                    stopped = should_stop()
                if stopped:
                    break
            if stopped:
                # Leaving the block closes the connection, so Bedrock stops generating. Output
                # tokens aren't reported mid-stream; estimate generously from the text so far.
                usage = stream.current_message_snapshot.usage
                input_tokens = usage.input_tokens
                output_tokens = max(usage.output_tokens or 0, math.ceil(len("".join(parts)) / 3))
                stop_reason = "stopped"
            else:
                final = stream.get_final_message()
                input_tokens, output_tokens = final.usage.input_tokens, final.usage.output_tokens
                stop_reason = final.stop_reason or "unknown"
    except Exception:
        log.exception("Claude stream failed")
        audit(p.deps, p.request_id, p.user_id, p.now, p.question, outcome="error", groups=p.groups, model=settings.model_id)
        if input_tokens or parts:
            UsageLedger(p.deps.table, settings.limits, settings.pricing).charge(
                p.user_id, p.now, input_tokens, max(output_tokens, math.ceil(len("".join(parts)) / 3))
            )
        send({"type": "error", "error": "The assistant had a problem answering. Try again."})
        return

    answer = "".join(parts).strip()
    if stop_reason == "refusal":
        answer = REFUSAL_ANSWER
        send({"type": "replace", "text": answer})
    elif stop_reason == "max_tokens":
        answer += CUT_OFF_NOTE
        send({"type": "delta", "text": CUT_OFF_NOTE})

    cited = [{"number": s.number, "title": s.title, "url": s.url} for s in cited_sources(answer, p.sources)]
    reply = {"role": "assistant", "content": answer, "sources": cited, "request_id": p.request_id}
    if stopped:
        reply["stopped"] = True
    p.chat["messages"] += [{"role": "user", "content": p.question}, reply]
    saved = True
    try:
        p.chats.save(p.user_id, p.chat, datetime.now(UTC))
    except ChatFull:
        saved = False

    cost = UsageLedger(p.deps.table, settings.limits, settings.pricing).charge(p.user_id, p.now, input_tokens, output_tokens)
    audit(
        p.deps,
        p.request_id,
        p.user_id,
        p.now,
        p.question,
        outcome=stop_reason,
        groups=p.groups,
        chat_id=p.chat["id"],
        answer=answer,
        retrieved=[{"url": s.url, "score": s.score} for s in p.sources],
        cited=[s["url"] for s in cited],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        micro_usd=cost,
        latency_ms=round((time.monotonic() - started) * 1000),
        model=settings.model_id,
    )
    send(
        {
            "type": "done",
            "chat_id": p.chat["id"],
            "title": p.chat["title"],
            "sources": cited,
            "request_id": p.request_id,
            "stopped": stopped,
            "saved": saved,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost / 1e6},
        }
    )
