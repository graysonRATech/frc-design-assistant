import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from chat_api.conversations import MAX_TURNS, Conversations, title_from
from chat_api.handler import Dependencies, Settings, lambda_handler
from chat_api.server import App, ChatRequestHandler, TokenVerifier, Unauthorized
from chat_api.streaming import Disconnected, Prepared, Rejected, prepare, run
from chat_api.usage import Limits, Pricing, user_key

USER = "student@example.org"
SETTINGS = Settings(
    knowledge_base_id="KB123",
    table_name="t",
    model_id="anthropic.claude-sonnet-5-5",
    endpoint="mantle",
    max_tokens=1500,
    effort="low",
    top_k=6,
    limits=Limits(user_daily_usd=0.50, monthly_usd=20),
    pricing=Pricing(2, 10),
    audit_retention_days=365,
    chat_retention_days=90,
)
RESULTS = [
    {"content": {"text": "Use #10-32 bolts."}, "metadata": {"title": "Fasteners", "url": "https://www.frcdesign.org/fasteners/"}, "score": 0.7},
    {"content": {"text": "Gear math."}, "metadata": {"title": "Gears", "url": "https://www.frcdesign.org/gears/"}, "score": 0.6},
]


class ConditionFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Table:
    """Just enough of a boto3 DynamoDB Table for the chat code."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def delete_item(self, Key):
        self.items.pop((Key["pk"], Key["sk"]), None)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, ExpressionAttributeNames=None):
        key = (Key["pk"], Key["sk"])
        if ConditionExpression and key not in self.items:
            raise ConditionFailed()
        item = self.items.setdefault(key, dict(Key))
        if UpdateExpression.startswith("SET"):
            item["title"] = ExpressionAttributeValues[":t"]
            return
        for name, placeholder in (("micro_usd", ":c"), ("input_tokens", ":i"), ("output_tokens", ":o"), ("requests", ":one")):
            item[name] = item.get(name, 0) + ExpressionAttributeValues[placeholder]

    def query(self, KeyConditionExpression, **kwargs):
        pk = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": [i for (p, _), i in self.items.items() if p == pk]}

    def audits(self):
        return [i for (p, _), i in self.items.items() if p.startswith("AUDIT#")]


class FakeStream:
    def __init__(self, chunks, stop_reason, on_chunk=None):
        self.chunks, self.stop_reason, self.on_chunk = chunks, stop_reason, on_chunk
        self.closed = False
        self.current_message_snapshot = SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=1))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    @property
    def text_stream(self):
        for i, chunk in enumerate(self.chunks):
            if self.on_chunk:
                self.on_chunk(i)
            yield chunk

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason, usage=SimpleNamespace(input_tokens=1000, output_tokens=200))


class FakeClaude:
    def __init__(self, chunks=("Use #10-32 ", "bolts [1]."), stop_reason="end_turn", on_chunk=None):
        self.calls, self.streams = [], []
        self.chunks, self.stop_reason, self.on_chunk = chunks, stop_reason, on_chunk
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        self.streams.append(FakeStream(self.chunks, self.stop_reason, self.on_chunk))
        return self.streams[-1]


def deps(**claude) -> Dependencies:
    runtime = SimpleNamespace(retrieve=lambda **kw: {"retrievalResults": RESULTS})
    return Dependencies(SETTINGS, runtime, FakeClaude(**claude), Table())


def ask(d, body, user=USER, should_stop=lambda: False):
    prepared = prepare(d, "req-1", user, ["student"], body)
    if isinstance(prepared, Rejected):
        return prepared, []
    events = []
    run(prepared, events.append, should_stop)
    return prepared, events


def test_new_chat_streams_saves_meters_and_audits():
    d = deps()
    prepared, events = ask(d, {"question": "  What bolts should I use?  "})
    assert [e["type"] for e in events] == ["start", "delta", "delta", "done"]
    done = events[-1]
    assert done["title"] == "What bolts should I use?" and done["stopped"] is False and done["saved"] is True
    assert done["sources"] == [{"number": 1, "title": "Fasteners", "url": "https://www.frcdesign.org/fasteners/"}]

    chat = Conversations(d.table, 90).get(USER, done["chat_id"])
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["content"] == "Use #10-32 bolts [1]." and chat["messages"][1]["request_id"] == "req-1"
    assert d.table.items[tuple(user_key(USER, datetime.now(UTC)).values())]["micro_usd"] == 1000 * 2 + 200 * 10
    assert d.table.audits()[0]["outcome"] == "end_turn" and d.table.audits()[0]["chat_id"] == done["chat_id"]
    saved = d.table.items[(f"CHATS#{USER}", done["chat_id"])]
    assert saved["expires_at"] > (datetime.now(UTC) + timedelta(days=89)).timestamp()


def test_follow_up_sends_saved_history_and_appends():
    d = deps()
    _, first = ask(d, {"question": "What bolts?"})
    chat_id = first[-1]["chat_id"]
    _, second = ask(d, {"question": "And nuts?", "chat_id": chat_id})
    assert second[-1]["chat_id"] == chat_id
    history = d.claude.calls[1]["messages"]
    assert history[0] == {"role": "user", "content": "What bolts?"} and history[1]["role"] == "assistant"
    assert len(Conversations(d.table, 90).get(USER, chat_id)["messages"]) == 4


def test_replace_last_regenerates_the_last_turn():
    d = deps()
    _, first = ask(d, {"question": "What bolts?"})
    chat_id = first[-1]["chat_id"]
    ask(d, {"question": "Which bolts, exactly?", "chat_id": chat_id, "replace_last": True})
    messages = Conversations(d.table, 90).get(USER, chat_id)["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["Which bolts, exactly?"]
    assert d.claude.calls[1]["messages"][:-1] == []  # no stale history


def test_stop_request_ends_the_stream_and_keeps_the_partial_answer(monkeypatch):
    monkeypatch.setattr("chat_api.streaming.STOP_POLL_SECONDS", 0)
    d = deps(chunks=("one ", "two ", "three"))
    _, events = ask(d, {"question": "Long one?"}, should_stop=lambda: True)
    assert [e["type"] for e in events] == ["start", "delta", "done"]
    assert events[-1]["stopped"] is True and d.claude.streams[0].closed
    chat = Conversations(d.table, 90).get(USER, events[-1]["chat_id"])
    assert chat["messages"][1] == {**chat["messages"][1], "content": "one", "stopped": True}
    assert d.table.audits()[0]["outcome"] == "stopped" and d.table.audits()[0]["input_tokens"] == 1000


def test_disconnect_stops_generating_but_still_saves():
    d = deps(chunks=("one ", "two ", "three"))
    prepared = prepare(d, "req-1", USER, ["student"], {"question": "Hi?"})
    sent = []

    def emit(event):
        if event["type"] == "delta":
            raise Disconnected
        sent.append(event)

    run(prepared, emit, lambda: False)
    assert [e["type"] for e in sent] == ["start"] and d.claude.streams[0].closed
    assert Conversations(d.table, 90).list(USER)[0]["title"] == "Hi?"


def test_refusal_replaces_the_answer():
    _, events = ask(deps(chunks=("Sure, here's how",), stop_reason="refusal"), {"question": "Bad?"})
    assert events[-2] == {"type": "replace", "text": "I can't help with that one. Try rephrasing, or ask a mentor."}


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"question": ""}, 400),
        ({"question": "x" * 2001}, 400),
        ({"question": "Hi", "chat_id": "20260101T000000-deadbeef"}, 404),
        ({"question": "Hi", "chat_id": "../../AUDIT"}, 404),
    ],
)
def test_bad_requests_are_rejected_before_streaming(body, status):
    rejected, _ = ask(deps(), body)
    assert isinstance(rejected, Rejected) and rejected.status == status


def test_daily_limit_rejects_with_429():
    d = deps()
    d.table.items[tuple(user_key(USER, datetime.now(UTC)).values())] = {"micro_usd": 500_000}
    rejected, _ = ask(d, {"question": "Hi"})
    assert (rejected.status, rejected.extra) == (429, {"limit": "daily"}) and not d.claude.calls


def test_full_chat_asks_for_a_new_one():
    d = deps()
    chats = Conversations(d.table, 90)
    turn = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    chats.save(USER, {"id": "20260101T000000-0000abcd", "title": "t", "messages": turn * MAX_TURNS}, datetime.now(UTC))
    rejected, _ = ask(d, {"question": "One more", "chat_id": "20260101T000000-0000abcd"})
    assert rejected.status == 409


def test_chats_are_private_to_each_user():
    d = deps()
    _, events = ask(d, {"question": "Mine"})
    rejected, _ = ask(d, {"question": "Peek", "chat_id": events[-1]["chat_id"]}, user="other@example.org")
    assert rejected.status == 404


def test_title_is_one_line_and_bounded():
    assert title_from("How do\n  gears   work?") == "How do gears work?"
    assert len(title_from("x" * 500)) == 80


# --- API Gateway routes for saved chats


def api_event(route, email=USER, chat_id=None, body=None):
    claims = {"sub": "abc", "email": email, "cognito:groups": "[student]"}
    event = {"routeKey": route, "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
    if chat_id:
        event["pathParameters"] = {"id": chat_id}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def call(d, *args, **kwargs):
    response = lambda_handler(api_event(*args, **kwargs), None, d)
    return response["statusCode"], json.loads(response["body"])


def test_chat_routes_list_open_rename_delete():
    d = deps()
    _, events = ask(d, {"question": "What bolts?"})
    chat_id = events[-1]["chat_id"]
    status, body = call(d, "GET /chats")
    assert status == 200 and body["chats"][0]["id"] == chat_id and "messages" not in body["chats"][0]
    status, body = call(d, "GET /chats/{id}", chat_id=chat_id)
    assert status == 200 and len(body["messages"]) == 2
    assert call(d, "PATCH /chats/{id}", chat_id=chat_id, body={"title": "Bolts"}) == (200, {"title": "Bolts"})
    assert call(d, "GET /chats")[1]["chats"][0]["title"] == "Bolts"
    assert call(d, "DELETE /chats/{id}", chat_id=chat_id) == (200, {"ok": True})
    assert call(d, "GET /chats/{id}", chat_id=chat_id)[0] == 404


def test_chat_routes_cannot_reach_other_users_chats():
    d = deps()
    _, events = ask(d, {"question": "Mine"})
    chat_id = events[-1]["chat_id"]
    assert call(d, "GET /chats/{id}", email="other@example.org", chat_id=chat_id)[0] == 404
    assert call(d, "PATCH /chats/{id}", email="other@example.org", chat_id=chat_id, body={"title": "x"})[0] == 404
    assert call(d, "GET /chats", email="other@example.org")[1] == {"chats": []}


def test_stop_route_flags_the_request():
    d = deps()
    assert call(d, "POST /chats/stop", body={"request_id": "req-9"}) == (200, {"ok": True})
    assert Conversations(d.table, 90).stop_requested(USER, "req-9")
    assert not Conversations(d.table, 90).stop_requested("other@example.org", "req-9")


def test_theme_setting_defaults_to_auto_and_is_per_user():
    d = deps()
    assert call(d, "GET /settings") == (200, {"theme": "auto"})
    assert call(d, "PUT /settings", body={"theme": "blueprint"}) == (200, {"theme": "blueprint"})
    assert call(d, "GET /settings") == (200, {"theme": "blueprint"})
    assert call(d, "GET /settings", email="other@example.org") == (200, {"theme": "auto"})


@pytest.mark.parametrize("body", [{"theme": "neon"}, {"theme": 3}, {}])
def test_theme_setting_rejects_unknown_themes(body):
    assert call(deps(), "PUT /settings", body=body)[0] == 400


# --- Token checks and the HTTP server

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
ISSUER_POOL = ("us-east-1", "us-east-1_TEST", "client-123")
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Jwks:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def token(**overrides):
    now = int(time.time())
    claims = {
        "sub": "abc",
        "email": USER,
        "cognito:groups": ["student"],
        "iss": ISSUER,
        "aud": "client-123",
        "token_use": "id",
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, KEY, algorithm="RS256")


def test_verifier_accepts_a_valid_id_token():
    assert TokenVerifier(*ISSUER_POOL, jwks_client=Jwks()).verify(f"Bearer {token()}") == (USER, ["student"])


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Basic abc",
        f"Bearer {token(aud='other-client')}",
        f"Bearer {token(iss='https://evil.example.org')}",
        f"Bearer {token(exp=int(time.time()) - 10)}",
        f"Bearer {token(token_use='access')}",
        f"Bearer {token(token_use=None)}",
        f"Bearer {jwt.encode({'sub': 'x', 'aud': 'client-123', 'iss': ISSUER, 'token_use': 'id', 'exp': 9999999999, 'iat': 1}, 'not-the-pool-key-' * 3, algorithm='HS256')}",
    ],
)
def test_verifier_rejects_bad_tokens(header):
    with pytest.raises(Unauthorized):
        TokenVerifier(*ISSUER_POOL, jwks_client=Jwks()).verify(header)


@pytest.fixture
def server():
    d = deps()
    ChatRequestHandler.app = App(d, TokenVerifier(*ISSUER_POOL, jwks_client=Jwks()))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ChatRequestHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/", d
    httpd.shutdown()


def post(url, body, auth=None):
    headers = {"content-type": "application/json", "x-amzn-lambda-context": json.dumps({"request_id": "lambda-req"})}
    if auth:
        headers["authorization"] = auth
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers.get("content-type"), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("content-type"), error.read().decode()


def test_server_streams_ndjson_events(server):
    url, d = server
    status, kind, text = post(url, {"question": "What bolts?"}, f"Bearer {token()}")
    events = [json.loads(line) for line in text.splitlines()]
    assert status == 200 and kind.startswith("application/x-ndjson")
    assert [e["type"] for e in events] == ["start", "delta", "delta", "done"]
    assert events[0]["request_id"] == "lambda-req"


def test_server_rejects_missing_tokens_and_bad_bodies(server):
    url, d = server
    assert post(url, {"question": "Hi"})[0] == 401
    assert post(url, {"question": ""}, f"Bearer {token()}")[0] == 400
    assert post(url, {"question": "Hi"}, f"Bearer {token(**{'cognito:groups': ['blocked']})}")[0] == 403
    assert not d.claude.calls


def test_server_answers_readiness_checks(server):
    url, _ = server
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.status == 200


# --- Lambda bundle


def test_stream_zip_has_an_executable_lf_start_script(tmp_path):
    from scripts.build_lambda import build_stream_zip

    bundle = tmp_path / "bundle"
    (bundle / "chat_api").mkdir(parents=True)
    (bundle / "chat_api" / "server.py").write_text("print('hi')\n")
    (bundle / ".requirements.sha256").write_text("x")
    first = build_stream_zip(bundle, tmp_path / "a.zip").read_bytes()
    (tmp_path / "a.sha256").unlink()
    assert build_stream_zip(bundle, tmp_path / "a.zip").read_bytes() == first  # deterministic
    with zipfile.ZipFile(tmp_path / "a.zip") as archive:
        info = archive.getinfo("run.sh")
        assert (info.external_attr >> 16) & 0o777 == 0o755 and info.create_system == 3
        assert b"\r" not in archive.read("run.sh") and archive.read("run.sh").startswith(b"#!/bin/sh\n")
        assert archive.namelist() == ["run.sh", "chat_api/server.py"]
