import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from chat_api import slack
from chat_api.slack import (
    HELP,
    NOT_ALLOWED,
    SlackError,
    events_handler,
    question_text,
    sources_footer,
    valid_signature,
    worker_handler,
)
from chat_api.usage import user_key
from tests.test_streaming import ConditionFailed, Table, deps

SECRET = "shh"
TEAM = "T0TORCH01"
NOW = 1_800_000_000


def signed(payload: dict, ts: int = NOW, secret: str = SECRET) -> dict:
    body = json.dumps(payload)
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest()
    return {"headers": {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sig}, "body": body}


class DedupeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise ConditionFailed()
        self.items[key] = Item


class FakeLambda:
    def __init__(self):
        self.jobs = []

    def invoke(self, FunctionName, InvocationType, Payload):
        assert InvocationType == "Event"
        self.jobs.append(json.loads(Payload))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SLACK_TEAM_ID", TEAM)
    monkeypatch.setenv("WORKER_FUNCTION", "worker")


def receive(payload, **kw):
    table, lam = kw.pop("table", DedupeTable()), kw.pop("lam", FakeLambda())
    request = kw.pop("request", None) or signed(payload)
    response = events_handler(request, None, table=table, lambda_client=lam, signing_secret=SECRET, now=kw.pop("now", NOW))
    return response, lam


def mention(event_id="Ev1", **event):
    return {
        "type": "event_callback",
        "team_id": TEAM,
        "event_id": event_id,
        "event": {"type": "app_mention", "user": "U1", "channel": "C1", "ts": "100.1", "text": "<@UBOT> what bolts?", **event},
    }


# ---- receiver ----


def test_signature_checks():
    body = '{"a":1}'
    good = "v0=" + hmac.new(b"s", f"v0:{NOW}:{body}".encode(), hashlib.sha256).hexdigest()
    assert valid_signature("s", str(NOW), body, good, NOW)
    assert not valid_signature("s", str(NOW), body + " ", good, NOW)
    assert not valid_signature("s", str(NOW), body, good, NOW + 301)  # replayed later
    assert not valid_signature("s", None, body, good, NOW)


def test_rejects_unsigned_and_answers_url_check():
    response, lam = receive(mention(), request=signed(mention(), secret="wrong"))
    assert response["statusCode"] == 401 and not lam.jobs
    response, _ = receive({"type": "url_verification", "challenge": "abc"})
    assert json.loads(response["body"]) == {"challenge": "abc"}


def test_mention_starts_the_worker_once_even_when_slack_retries():
    table, lam = DedupeTable(), FakeLambda()
    receive(mention(), table=table, lam=lam)
    receive(mention(), table=table, lam=lam)
    assert lam.jobs == [{"team": TEAM, "channel": "C1", "user": "U1", "text": "<@UBOT> what bolts?", "ts": "100.1", "thread_ts": "100.1", "where": "channel"}]


def test_replies_in_the_existing_thread_and_handles_dms():
    _, lam = receive(mention(thread_ts="90.0"))
    assert lam.jobs[0]["thread_ts"] == "90.0"
    dm = {"type": "event_callback", "team_id": TEAM, "event_id": "Ev2",
          "event": {"type": "message", "channel_type": "im", "user": "U1", "channel": "D1", "ts": "5.5", "text": "hi"}}  # fmt: skip
    _, lam = receive(dm)
    assert lam.jobs[0]["where"] == "dm" and lam.jobs[0]["thread_ts"] == "5.5"


@pytest.mark.parametrize(
    "payload",
    [
        mention(bot_id="B1"),  # a bot, e.g. this one
        mention(subtype="message_changed"),
        {**mention(), "team_id": "T0OTHER99"},  # another workspace
        {"type": "event_callback", "team_id": TEAM, "event_id": "Ev3",
         "event": {"type": "message", "channel_type": "channel", "user": "U1", "channel": "C1", "ts": "1.0", "text": "chatter"}},
    ],
)  # fmt: skip
def test_ignores_everything_that_is_not_a_question_for_the_bot(payload):
    response, lam = receive(payload)
    assert response["statusCode"] == 200 and not lam.jobs


def test_question_text_strips_slack_markup():
    text = "<@UBOT>  what about <https://www.frcdesign.org/x|this guide> &amp; <#C1|cad> <!here> 10&lt;12?"
    assert question_text(text) == "what about this guide & 10<12?"


# ---- worker ----

MEMBER = {"id": "U1", "team_id": TEAM, "profile": {"email": "Student@Example.org"}}


class FakeSlack:
    def __init__(self, user=MEMBER, fail=None):
        self.user, self.fail, self.calls = user, fail or {}, []

    def call(self, method, **args):
        self.calls.append((method, args))
        if method in self.fail:
            raise SlackError(method, self.fail[method])
        if method == "users.info":
            return {"ok": True, "user": self.user}
        return {"ok": True, "ts": "200.2"}

    def methods(self):
        return [m for m, _ in self.calls]


def job(**kw):
    return {"team": TEAM, "channel": "C1", "user": "U1", "text": "<@UBOT> What bolts?", "ts": "100.1", "thread_ts": "100.1", "where": "channel", **kw}


def allowed_deps(**claude):
    d = deps(**claude)
    d.table.put_item({"pk": "ALLOW", "sk": "@example.org", "role": "student"})
    return d


def test_member_on_the_allowlist_gets_a_streamed_cited_answer():
    d, sl = allowed_deps(), FakeSlack()
    worker_handler(job(), None, deps=d, slack=sl)
    assert sl.methods() == ["users.info", "chat.startStream", "chat.stopStream"]
    start = sl.calls[1][1]
    assert start == {"channel": "C1", "thread_ts": "100.1", "recipient_user_id": "U1", "recipient_team_id": TEAM,
                     "markdown_text": "Use #10-32 bolts [1]."}  # fmt: skip
    assert sl.calls[2][1]["markdown_text"] == "\n\n**Sources**\n1. [Fasteners](https://www.frcdesign.org/fasteners/)"
    thread = d.table.items[("SLACK#C1", "100.1")]
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"] and thread["title"] == "What bolts?"
    email = "student@example.org"  # usage is shared with the website by email
    assert d.table.items[tuple(user_key(email, datetime.now(UTC)).values())]["requests"] == 1
    assert d.table.audits()[0]["user"] == email


def test_follow_up_in_the_thread_sends_its_history():
    d = allowed_deps()
    worker_handler(job(), None, deps=d, slack=FakeSlack())
    worker_handler(job(text="<@UBOT> and nuts?"), None, deps=d, slack=FakeSlack())
    assert d.claude.calls[1]["messages"][0] == {"role": "user", "content": "What bolts?"}
    assert len(d.table.items[("SLACK#C1", "100.1")]["messages"]) == 4


@pytest.mark.parametrize(
    "user",
    [
        {**MEMBER, "is_restricted": True},  # guest
        {**MEMBER, "is_stranger": True},  # someone in a shared channel
        {**MEMBER, "team_id": "T0OTHER99"},
        {**MEMBER, "deleted": True},
        {**MEMBER, "profile": {"email": "someone@elsewhere.org"}},  # not on the allowlist
        {**MEMBER, "profile": {}},
    ],
)
def test_everyone_else_gets_a_private_no(user):
    d, sl = allowed_deps(), FakeSlack(user=user)
    worker_handler(job(), None, deps=d, slack=sl)
    assert sl.methods() == ["users.info", "chat.postEphemeral"]
    assert sl.calls[1][1]["text"] == NOT_ALLOWED and sl.calls[1][1]["user"] == "U1"
    assert "thread_ts" not in sl.calls[1][1]  # inline in the channel, where the asker will see it
    assert not d.claude.calls


def test_refusal_says_why_in_the_log_without_the_email(caplog):
    caplog.set_level("INFO")
    worker_handler(job(), None, deps=allowed_deps(), slack=FakeSlack(user={**MEMBER, "profile": {"email": "someone@elsewhere.org"}}))
    worker_handler(job(), None, deps=allowed_deps(), slack=FakeSlack(user={**MEMBER, "is_restricted": True}))
    assert "email not on the access list" in caplog.text
    assert "multi-channel guest" in caplog.text
    assert "elsewhere.org" not in caplog.text


def test_private_replies_to_a_follow_up_stay_in_its_thread():
    d, sl = allowed_deps(), FakeSlack(user={**MEMBER, "profile": {"email": "someone@elsewhere.org"}})
    worker_handler(job(ts="100.9"), None, deps=d, slack=sl)
    assert sl.calls[1][1]["thread_ts"] == "100.1"


def test_blocked_email_entry_beats_the_domain():
    d, sl = allowed_deps(), FakeSlack()
    d.table.put_item({"pk": "ALLOW", "sk": "student@example.org", "role": "blocked"})
    worker_handler(job(), None, deps=d, slack=sl)
    assert sl.calls[1][1]["text"] == NOT_ALLOWED


def test_empty_mention_gets_help_and_dm_replies_are_normal_messages():
    sl = FakeSlack()
    worker_handler(job(text="<@UBOT>", where="dm", channel="D1"), None, deps=allowed_deps(), slack=sl)
    assert sl.calls[-1] == ("chat.postMessage", {"channel": "D1", "thread_ts": "100.1", "text": HELP})


def test_daily_limit_is_shared_with_the_website():
    d, sl = allowed_deps(), FakeSlack()
    d.table.put_item({**user_key("student@example.org", datetime.now(UTC)), "micro_usd": 10**6})
    worker_handler(job(), None, deps=d, slack=sl)
    assert sl.calls[-1][1]["text"].startswith("You've reached today's question limit")
    assert not d.claude.calls


def test_long_answers_stream_in_pieces(monkeypatch):
    monkeypatch.setattr(slack, "FLUSH_SECONDS", 0)
    sl = FakeSlack()
    worker_handler(job(), None, deps=allowed_deps(chunks=("one ", "two ", "three")), slack=sl)
    assert sl.methods() == ["users.info", "chat.startStream", "chat.appendStream", "chat.appendStream", "chat.stopStream"]


def test_stop_button_in_slack_stops_generating_and_keeps_the_partial_answer(monkeypatch):
    monkeypatch.setattr(slack, "FLUSH_SECONDS", 0)
    d, sl = allowed_deps(chunks=("one ", "two ", "three")), FakeSlack(fail={"chat.appendStream": "stopped_by_user"})
    worker_handler(job(), None, deps=d, slack=sl)
    assert d.claude.streams[0].closed and "chat.stopStream" not in sl.methods()
    assert d.table.items[("SLACK#C1", "100.1")]["messages"][1]["content"] == "one two"


def test_unstreamable_channel_falls_back_to_a_short_note():
    sl = FakeSlack(fail={"chat.startStream": "channel_type_not_supported"})
    worker_handler(job(), None, deps=allowed_deps(), slack=sl)
    assert sl.calls[-1][0] == "chat.postEphemeral" and "couldn't post an answer" in sl.calls[-1][1]["text"]


def test_footer_marks_stopped_answers():
    assert sources_footer([], True) == "\n\n_Stopped._"
    assert sources_footer([{"number": 2, "title": "A [b]", "url": "u"}], False) == "\n\n**Sources**\n2. [A (b)](u)"


def test_thread_store_keeps_threads_apart():
    table = Table()
    one = slack.ThreadStore(table, 90, "C1", "1.0")
    assert one.get("x", one.chat_id)["messages"] == []
    one.save("x", {"id": one.chat_id, "title": "", "messages": [{"role": "user", "content": "q"}]}, datetime.now(UTC))
    assert slack.ThreadStore(table, 90, "C1", "2.0").get("x", "")["messages"] == []
    assert one.get("x", "")["messages"] == [{"role": "user", "content": "q"}]
