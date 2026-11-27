"""Slack bot: mention @TORCH in a channel, or DM it, and the answer streams into a thread.

Two Lambdas share this module:

- `events_handler` sits behind a public function URL that Slack's Events API posts to. It checks
  Slack's request signature, answers Slack's URL check, ignores anything that isn't a question
  for the bot, and drops Slack's retries (each event id is handled once). It must reply within
  Slack's 3-second limit, so it hands the question to the worker with an async invoke.
- `worker_handler` looks up the asker's Slack email, applies the same allowlist, roles, daily
  limits and audit log as the website, and streams the answer with chat.startStream /
  appendStream / stopStream. It reuses streaming.prepare/run, so answers match the web page.

Who gets answers: full members of the configured workspace whose Slack email is on the
allowlist (an email entry, or a domain entry; Slack confirms an address before it joins a
workspace, and the workspace admin controls who joins). Guests, people from other workspaces in
shared channels, bots and deactivated accounts never do.

Each Slack thread is its own conversation, stored under pk="SLACK#<channel>", sk=<thread ts>,
and expires like saved chats. Usage and audit entries are keyed by the asker's email, so the
web page and Slack share one daily limit.

Secrets Manager holds {"bot_token": "xoxb-...", "signing_secret": "..."} under SLACK_SECRET_NAME.
"""

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache

from .conversations import MAX_ITEM_BYTES, ChatFull, plain, title_from
from .streaming import Disconnected, Rejected, prepare, run

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

MAX_SKEW_SECONDS = 300  # Slack's recommended replay window for signed requests
STREAM_CHAR_LIMIT = 12_000  # markdown_text across one whole stream
FOOTER_RESERVE = 1_500  # kept free for the sources list
FLUSH_SECONDS = 1.0  # appendStream is rate-limited; send text about once a second

NOT_ALLOWED = (
    "Sorry, your Slack account isn't on TORCH's access list for the design assistant. "
    "Ask a mentor to add the email on your Slack profile."
)
HELP = "Ask me an FRC design, CAD or fabrication question, like *@TORCH what bolts should we use for the drivetrain?*"


# ---- Slack plumbing -----------------------------------------------------------------------


class SlackError(Exception):
    def __init__(self, method: str, code: str):
        super().__init__(f"{method}: {code}")
        self.code = code


class SlackClient:
    """The few Web API calls the bot makes, over urllib (no SDK dependency)."""

    def __init__(self, token: str, base: str = "https://slack.com/api/"):
        self.token = token
        self.base = base

    def call(self, method: str, **args) -> dict:
        if method == "users.info":  # read methods take form arguments, not JSON
            data = urllib.parse.urlencode(args).encode()
            content_type = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(args).encode()
            content_type = "application/json; charset=utf-8"
        request = urllib.request.Request(
            self.base + method, data=data, headers={"authorization": f"Bearer {self.token}", "content-type": content_type}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
        if not body.get("ok"):
            raise SlackError(method, str(body.get("error", "unknown_error")))
        return body


def valid_signature(signing_secret: str, timestamp: str | None, body: str, signature: str | None, now: float) -> bool:
    """Slack's v0 request signature: HMAC-SHA256 over "v0:<timestamp>:<raw body>"."""
    if not timestamp or not signature:
        return False
    try:
        if abs(now - int(timestamp)) > MAX_SKEW_SECONDS:
            return False
    except ValueError:
        return False
    expected = "v0=" + hmac.new(signing_secret.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


_MENTION = re.compile(r"<@[A-Z0-9]+(?:\|[^>]*)?>")
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")
_SPECIAL = re.compile(r"<[!#][^>]*>")  # <!here>, <#C123|channel>


def question_text(slack_text: str) -> str:
    """Slack's message markup to plain text: drop mentions, unwrap links, unescape &amp; etc."""
    text = _MENTION.sub(" ", slack_text or "")
    text = _LINK.sub(lambda m: m.group(2) or m.group(1), text)
    text = _SPECIAL.sub(" ", text)
    return " ".join(html.unescape(text).split())


def job_from(payload: dict) -> dict | None:
    """The question in an Events API callback, or None when it isn't one for the bot."""
    event = payload.get("event") or {}
    kind = event.get("type")
    if event.get("bot_id") or event.get("subtype") or not event.get("user"):
        return None  # bots (including this one), edits, joins and other housekeeping
    if kind == "app_mention":
        where = "channel"
    elif kind == "message" and event.get("channel_type") == "im":
        where = "dm"
    else:
        return None
    return {
        "team": payload.get("team_id", ""),
        "channel": event["channel"],
        "user": event["user"],
        "text": event.get("text", ""),
        "ts": event["ts"],
        "thread_ts": event.get("thread_ts") or event["ts"],  # streaming always replies in a thread
        "where": where,
    }


# ---- Events receiver ----------------------------------------------------------------------


@cache
def _secret() -> dict:
    import boto3

    value = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["SLACK_SECRET_NAME"])
    return json.loads(value["SecretString"])


@cache
def _aws():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]), boto3.client("lambda")


def first_delivery(table, event_id: str, now: datetime) -> bool:
    """Record the event id; False if it was already seen (a Slack retry)."""
    try:
        table.put_item(
            Item={"pk": f"SLACKEVENT#{event_id[:64]}", "sk": "seen", "expires_at": int((now + timedelta(days=1)).timestamp())},
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as error:  # botocore ClientError, without importing botocore here
        if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def events_handler(event, context, table=None, lambda_client=None, signing_secret=None, now=None):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    secret = signing_secret or _secret()["signing_secret"]
    if not valid_signature(secret, headers.get("x-slack-request-timestamp"), body, headers.get("x-slack-signature"), now or time.time()):
        return _http(401, {"error": "bad signature"})
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _http(400, {"error": "Body must be JSON"})

    if payload.get("type") == "url_verification":
        return _http(200, {"challenge": payload.get("challenge", "")})
    if payload.get("type") != "event_callback":
        return _http(200, {"ok": True})
    if payload.get("team_id") != os.environ.get("SLACK_TEAM_ID"):
        log.warning("ignored event from another workspace")
        return _http(200, {"ok": True})

    job = job_from(payload)
    if job:
        if table is None or lambda_client is None:
            table, lambda_client = _aws()
        if first_delivery(table, str(payload.get("event_id", "")), datetime.now(UTC)):
            lambda_client.invoke(FunctionName=os.environ["WORKER_FUNCTION"], InvocationType="Event", Payload=json.dumps(job).encode())
    return _http(200, {"ok": True})


def _http(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


# ---- Worker -------------------------------------------------------------------------------


class ThreadStore:
    """One Slack thread as a conversation, with the get/save methods streaming.prepare/run use."""

    def __init__(self, table, retention_days: int, channel: str, thread_ts: str):
        self.table = table
        self.retention_days = retention_days
        self.key = {"pk": f"SLACK#{channel}", "sk": thread_ts}
        self.chat_id = f"slack-{channel}-{thread_ts}"

    def get(self, user: str, chat_id: str) -> dict:
        item = self.table.get_item(Key=self.key, ConsistentRead=True).get("Item") or {}
        return {
            "id": self.chat_id,
            "title": item.get("title", ""),
            "created_at": item.get("created_at", ""),
            "messages": plain(item.get("messages", [])),
        }

    def save(self, user: str, chat: dict, now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        first_question = next((m["content"] for m in chat["messages"] if m["role"] == "user"), "")
        item = {
            **self.key,
            "title": chat.get("title") or title_from(first_question),
            "created_at": chat.get("created_at") or stamp,
            "updated_at": stamp,
            "expires_at": int((now + timedelta(days=self.retention_days)).timestamp()),
            "messages": chat["messages"],
        }
        encoded = json.dumps(item)
        if len(encoded.encode()) > MAX_ITEM_BYTES:
            raise ChatFull(self.chat_id)
        self.table.put_item(Item=json.loads(encoded, parse_float=Decimal))


def member_email(slack: SlackClient, user_id: str, team_id: str) -> str | None:
    """The email of a full member of our workspace, or None for anyone else."""
    user = slack.call("users.info", user=user_id)["user"]
    reasons = {
        "deleted": user.get("deleted"),
        "bot": user.get("is_bot"),
        "multi-channel guest": user.get("is_restricted"),
        "single-channel guest": user.get("is_ultra_restricted"),
        "another workspace": user.get("is_stranger") or user.get("team_id") != team_id,
    }
    refused = [reason for reason, applies in reasons.items() if applies]
    if refused:
        log.info("Slack user refused: %s", ", ".join(refused))
        return None
    email = str((user.get("profile") or {}).get("email") or "").strip().lower()
    if not email:
        log.info("Slack user refused: no email visible (check the users:read.email scope)")
    return email or None


class SlackReply:
    """Turns streaming.run events into one streamed Slack message in the question's thread."""

    def __init__(self, slack: SlackClient, job: dict, flush_seconds: float | None = None):
        self.slack, self.job = slack, job
        self.flush_seconds = FLUSH_SECONDS if flush_seconds is None else flush_seconds
        self.ts = None  # the streaming message, once started
        self.buffer = ""
        self.sent = 0
        self.last_flush = time.monotonic()
        self.finished = False
        self.stopped_by_user = False
        self.failed = False  # Slack refused the stream (e.g. a channel type it can't stream to)

    def emit(self, event: dict) -> None:
        kind = event["type"]
        if kind == "delta":
            self.buffer += event["text"]
            if time.monotonic() - self.last_flush >= self.flush_seconds:
                self._flush()
        elif kind == "replace":  # a refusal: rarely after any text, but say so if it is
            self.buffer = event["text"] if self.ts is None else self.buffer + "\n\n" + event["text"]
        elif kind == "done":
            footer = sources_footer(event["sources"], event["stopped"])
            self._finish(footer)
        elif kind == "error":
            self._finish(f"\n\n:warning: {event['error']}")

    def close(self) -> None:
        """Make sure a started stream is finalized, whatever happened."""
        if self.ts and not self.finished:
            self._call_quietly("chat.stopStream", channel=self.job["channel"], ts=self.ts)
            self.finished = True

    def _clip(self, text: str, reserve: int = FOOTER_RESERVE) -> str:
        room = max(0, STREAM_CHAR_LIMIT - reserve - self.sent)
        return text[:room]

    def _flush(self) -> None:
        text, self.buffer = self._clip(self.buffer), ""
        self.last_flush = time.monotonic()
        if not text:
            return
        try:
            if self.ts is None:
                started = self.slack.call(
                    "chat.startStream",
                    channel=self.job["channel"],
                    thread_ts=self.job["thread_ts"],
                    recipient_user_id=self.job["user"],
                    recipient_team_id=self.job["team"],
                    markdown_text=text,
                )
                self.ts = started["ts"]
            else:
                self.slack.call("chat.appendStream", channel=self.job["channel"], ts=self.ts, markdown_text=text)
        except SlackError as error:
            if error.code in ("stopped_by_user", "message_not_in_streaming_state"):
                self.stopped_by_user = error.code == "stopped_by_user"
                self.finished = True
            else:
                self.failed = True
                log.error("Slack streaming failed: %s", error)
            raise Disconnected from error  # streaming.run stops generating and still saves
        self.sent += len(text)

    def _finish(self, footer: str) -> None:
        try:
            self._flush()
        except Disconnected:
            return
        footer = self._clip(footer, reserve=0)
        if self.ts is None:  # nothing streamed (empty answer, or an error before any text)
            self.ts = self._call_quietly(
                "chat.startStream",
                channel=self.job["channel"],
                thread_ts=self.job["thread_ts"],
                recipient_user_id=self.job["user"],
                recipient_team_id=self.job["team"],
                markdown_text=footer.strip() or "_(No answer.)_",
            ).get("ts")
            footer = ""
        if self.ts:
            args = {"markdown_text": footer} if footer else {}
            self._call_quietly("chat.stopStream", channel=self.job["channel"], ts=self.ts, **args)
        self.finished = True

    def _call_quietly(self, method: str, **args) -> dict:
        try:
            return self.slack.call(method, **args)
        except SlackError as error:
            log.error("Slack %s failed: %s", method, error.code)
            return {}


def sources_footer(sources: list[dict], stopped: bool) -> str:
    parts = []
    if stopped:
        parts.append("\n\n_Stopped._")
    if sources:
        lines = "\n".join(f"{s['number']}. [{_md_label(s['title'])}]({s['url']})" for s in sources)
        parts.append(f"\n\n**Sources**\n{lines}")
    return "".join(parts)


def _md_label(title: str) -> str:
    return title.replace("[", "(").replace("]", ")")


def say(slack: SlackClient, job: dict, text: str) -> None:
    """A short reply only the asker sees in channels; a normal thread reply in DMs."""
    try:
        if job["where"] == "dm":
            slack.call("chat.postMessage", channel=job["channel"], thread_ts=job["thread_ts"], text=text)
        else:
            # Inline where they asked: an ephemeral note inside a thread is easy to miss, because
            # Slack doesn't show the thread's reply count for it. Mid-thread follow-ups stay there.
            in_thread = job["thread_ts"] != job.get("ts", job["thread_ts"])
            extra = {"thread_ts": job["thread_ts"]} if in_thread else {}
            slack.call("chat.postEphemeral", channel=job["channel"], user=job["user"], text=text, **extra)
    except SlackError as error:
        log.error("Slack reply failed: %s", error.code)


def worker_handler(event, context, deps=None, slack=None):
    from auth_triggers.handler import allowlisted_role

    from .handler import _default_dependencies

    job = event
    deps = deps or _default_dependencies(claude_timeout=100.0)
    slack = slack or SlackClient(_secret()["bot_token"])
    request_id = getattr(context, "aws_request_id", None) or f"slack-{time.time_ns()}"

    email = member_email(slack, job["user"], os.environ.get("SLACK_TEAM_ID", job["team"]))
    role = allowlisted_role(deps.table, email, verified=True) if email else None
    if not role:
        if email:
            log.info("Slack user refused: email not on the access list")
        return say(slack, job, NOT_ALLOWED)

    question = question_text(job["text"])
    if not question:
        return say(slack, job, HELP)
    store = ThreadStore(deps.table, deps.settings.chat_retention_days, job["channel"], job["thread_ts"])
    prepared = prepare(deps, request_id, email, [role], {"question": question, "chat_id": store.chat_id}, chats=store)
    if isinstance(prepared, Rejected):
        error = "This thread is full. Start a new thread to keep going." if prepared.status == 409 else prepared.error
        return say(slack, job, error)

    reply = SlackReply(slack, job)
    try:
        run(prepared, reply.emit, lambda: reply.stopped_by_user)
    finally:
        reply.close()
    if reply.failed and reply.ts is None:
        say(slack, job, "Sorry, I couldn't post an answer here. Try asking in a DM.")
