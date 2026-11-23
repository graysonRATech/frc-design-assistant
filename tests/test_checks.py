import json
import logging
from types import SimpleNamespace

import pytest

from chat_api.handler import Dependencies, lambda_handler
from scripts.smoke_test import SmokeFailed, check
from tests.test_streaming import SETTINGS, FakeClaude, Table, deps

CHECK = {"user": "daily-check", "question": "What bolts?", "stream": True}


def body(response):
    return json.loads(response["body"])


def test_stream_check_answers_through_the_streaming_pipeline_and_cleans_up():
    d = deps()
    response = lambda_handler(CHECK, None, d)
    assert response["statusCode"] == 200
    assert body(response)["answer"] == "Use #10-32 bolts [1]." and body(response)["sources"][0]["title"] == "Fasteners"
    assert d.claude.calls  # messages.stream, the call the web page and Slack make
    assert not [k for k in d.table.items if k[0].startswith("CHATS#")]  # no leftover saved chat
    assert d.table.audits()[0]["user"] == "cli:daily-check"


def test_stream_check_failure_is_logged_for_the_alarm(caplog):
    d = deps()
    d.claude.messages = SimpleNamespace(stream=lambda **kw: (_ for _ in ()).throw(PermissionError("403")))
    with caplog.at_level(logging.ERROR):
        response = lambda_handler(CHECK, None, d)
    assert response["statusCode"] == 502 and any(r.levelno == logging.ERROR for r in caplog.records)


def test_stream_check_needs_retrieved_sources(caplog):
    d = Dependencies(SETTINGS, SimpleNamespace(retrieve=lambda **kw: {"retrievalResults": []}), FakeClaude(), Table())
    with caplog.at_level(logging.ERROR):
        response = lambda_handler(CHECK, None, d)
    assert response["statusCode"] == 502 and "Knowledge Base" in caplog.text


def test_api_requests_cannot_switch_to_check_mode():
    d = deps()
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"email": "s@x.org", "cognito:groups": "[student]"}}}},
             "routeKey": "POST /chat", "body": json.dumps({"question": "hi"}), "stream": True}  # fmt: skip
    d.claude.messages.create = lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1, output_tokens=1)
    )
    assert lambda_handler(event, None, d)["statusCode"] == 200 and not d.claude.calls


OUTPUTS = {"WebUrl": "https://site/", "StreamUrl": "https://stream/", "ChatFunctionName": "chat"}


def fake_status(page=200, stream=401, csp=True):
    def status(url, method="GET", data=None):
        if url == OUTPUTS["WebUrl"]:
            return page, ({"Content-Security-Policy": "x"} if csp else {})
        return stream, {}

    return status


def answered(**overrides):
    payload = {"answer": "Most FRC robots use #10-32 bolts because they are strong enough [1].", "sources": [{"number": 1}], "usage": {"cost_usd": 0.004}}
    return lambda name, p: {"statusCode": 200, "body": json.dumps({**payload, **overrides})}


def test_smoke_check_passes_on_a_healthy_stack():
    report = check(OUTPUTS, answered(), fake_status())
    assert len(report) == 3 and "1 cited source" in report[2]


@pytest.mark.parametrize(
    ("invoke", "status", "message"),
    [
        (answered(), fake_status(csp=False), "chat page"),
        (answered(), fake_status(stream=200), "expected 401"),
        (lambda n, p: {"statusCode": 502, "body": json.dumps({"error": "boom"})}, fake_status(), "boom"),
        (answered(sources=[]), fake_status(), "uncited"),
    ],
)
def test_smoke_check_fails_loudly(invoke, status, message):
    with pytest.raises(SmokeFailed, match=message):
        check(OUTPUTS, invoke, status)
