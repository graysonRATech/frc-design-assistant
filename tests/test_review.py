import json
from datetime import UTC, datetime, timedelta

import pytest
from boto3.dynamodb.conditions import AttributeNotExists, Between, ConditionBase, Equals

from chat_api import review
from chat_api.handler import Dependencies, lambda_handler
from test_chat_api import RESULTS, SETTINGS, FakeClaude, FakeRuntime


def matches(condition: ConditionBase, item: dict) -> bool:
    """Evaluate the boto3 conditions review.py uses against a plain dict."""
    expr = condition.get_expression()
    values = expr["values"]
    if expr["operator"] == "AND":
        return matches(values[0], item) and matches(values[1], item)
    if expr["operator"] == "OR":
        return matches(values[0], item) or matches(values[1], item)
    name = values[0].name
    if isinstance(condition, AttributeNotExists):
        return name not in item
    if isinstance(condition, Equals):
        return item.get(name) == values[1]
    if isinstance(condition, Between):
        return name in item and values[1] <= item[name] <= values[2]
    raise NotImplementedError(expr["operator"])


class ConditionalCheckFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Table:
    """Enough of a DynamoDB table for queries with filters, paging and conditional updates."""

    def __init__(self, items=(), page_size=3):
        self.items = {(i["pk"], i["sk"]): dict(i) for i in items}
        self.page_size = page_size
        self.queries = 0

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, **_):
        key = (Key["pk"], Key["sk"])
        if ConditionExpression and key not in self.items:
            raise ConditionalCheckFailed()
        values = ExpressionAttributeValues
        self.items[key].update(review_status=values[":s"], review_note=values[":n"], reviewed_by=values[":r"], reviewed_at=values[":t"])

    def query(self, KeyConditionExpression, FilterExpression=None, ScanIndexForward=True, Limit=None, ExclusiveStartKey=None, **_):
        self.queries += 1
        rows = sorted((i for i in self.items.values() if matches(KeyConditionExpression, i)), key=lambda i: i["sk"], reverse=not ScanIndexForward)
        if ExclusiveStartKey:
            rows = rows[[r["sk"] for r in rows].index(ExclusiveStartKey["sk"]) + 1 :]
        page = rows[: min(Limit or self.page_size, self.page_size)]  # DynamoDB filters after reading a page
        result = {"Items": [r for r in page if FilterExpression is None or matches(FilterExpression, r)]}
        if len(rows) > len(page):
            result["LastEvaluatedKey"] = {"pk": page[-1]["pk"], "sk": page[-1]["sk"]}
        return result


NOW = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)


def stamp(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")


def audit(user, request_id, t, **fields):
    return {"pk": f"AUDIT#{user}", "sk": f"{stamp(t)}#{request_id}", "request_id": request_id, "user": user, "question": "Q?", **fields}


def feedback(request_id, t, rating="down", user="s@x.org", **fields):
    return {"pk": "FEEDBACK", "sk": f"{stamp(t)}#{request_id}", "request_id": request_id, "user": user, "rating": rating, "comment": "", **fields}


def event(route, email="mentor@x.org", group="mentor", body=None, params=None):
    claims = {"sub": "abc", "email": email, "cognito:groups": f"[{group}]"}
    return {
        "routeKey": route,
        "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
        "body": json.dumps(body or {}),
        "queryStringParameters": params,
    }


def deps(table):
    return Dependencies(SETTINGS, FakeRuntime(RESULTS), FakeClaude("x"), table)


def test_find_answer_picks_the_rated_answer_among_many():
    table = Table([audit("s@x.org", f"r{i}", NOW - timedelta(hours=i), answer=f"a{i}") for i in range(8)], page_size=2)
    assert review.find_answer(table, "s@x.org", "r5", NOW, 90)["answer"] == "a5"
    assert review.find_answer(table, "s@x.org", "nope", NOW, 90) == {}
    assert review.find_answer(table, "other@x.org", "r5", NOW, 90) == {}


def test_feedback_copies_the_answer_it_rates():
    t = datetime.now(UTC) - timedelta(minutes=5)
    sources = [{"number": 1, "title": "Fasteners", "url": "https://frcdesign.org/f"}]
    table = Table([audit("student@example.org", "req-1", t, answer="Use 10-32.", sources=sources, model="haiku")])
    body = {"request_id": "req-1", "rating": "down", "comment": "wrong size"}
    response = lambda_handler(event("POST /feedback", "student@example.org", "student", body), None, deps(table))
    assert response["statusCode"] == 200
    [item] = [i for (pk, _), i in table.items.items() if pk == "FEEDBACK"]
    assert item["question"] == "Q?" and item["answer"] == "Use 10-32." and item["sources"] == sources
    assert item["user"] == "student@example.org" and item["comment"] == "wrong size"


def test_feedback_on_someone_elses_answer_copies_nothing():
    table = Table([audit("other@x.org", "req-1", datetime.now(UTC), answer="secret")])
    body = {"request_id": "req-1", "rating": "down"}
    lambda_handler(event("POST /feedback", "student@example.org", "student", body), None, deps(table))
    [item] = [i for (pk, _), i in table.items.items() if pk == "FEEDBACK"]
    assert "answer" not in item


def test_students_cant_see_the_review_list():
    response = lambda_handler(event("GET /review", "s@x.org", "student"), None, deps(Table()))
    assert response["statusCode"] == 403


def test_review_lists_open_thumbs_down_newest_first():
    table = Table(
        [
            feedback("r1", NOW - timedelta(hours=3), question="old", answer="a"),
            feedback("r2", NOW - timedelta(hours=2), rating="up", question="liked", answer="a"),
            feedback("r3", NOW - timedelta(hours=1), question="newer", answer="a", review_status="done"),
            feedback("r4", NOW, question="newest", answer="a"),
        ]
    )
    response = lambda_handler(event("GET /review"), None, deps(table))
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [i["question"] for i in body["items"]] == ["newest", "old"] and body["next"] is None
    assert body["items"][0]["status"] == "open" and body["items"][0]["user"] == "s@x.org"

    everything = json.loads(lambda_handler(event("GET /review", params={"rating": "all", "status": "all"}), None, deps(table))["body"])
    assert len(everything["items"]) == 4
    done = json.loads(lambda_handler(event("GET /review", params={"status": "done"}), None, deps(table))["body"])
    assert [i["question"] for i in done["items"]] == ["newer"]
    assert lambda_handler(event("GET /review", params={"rating": "meh"}), None, deps(table))["statusCode"] == 400


def test_review_pages_through_long_lists(monkeypatch):
    monkeypatch.setattr(review, "PAGE_SIZE", 4)
    table = Table([feedback(f"r{i:02}", NOW - timedelta(minutes=i), question=f"q{i}", answer="a") for i in range(10)])
    seen, cursor = [], None
    for _ in range(5):
        page = review.list_feedback(table, "down", "open", 90, cursor)
        seen += [i["question"] for i in page["items"]]
        cursor = page["next"]
        if not cursor:
            break
    assert seen == [f"q{i}" for i in range(10)]


def test_older_feedback_is_joined_to_its_answer_at_review_time():
    rated = NOW - timedelta(days=2)
    table = Table(
        [
            audit("s@x.org", "r1", rated - timedelta(minutes=3), answer="The limit is 120 lb.", cited=["https://x/#R103"]),
            feedback("r1", rated, comment="it's 115"),
        ]
    )
    [item] = review.list_feedback(table, "down", "open", 90)["items"]
    assert item["question"] == "Q?" and item["answer"] == "The limit is 120 lb."
    assert item["sources"] == [{"number": 1, "title": "", "url": "https://x/#R103"}]


def test_mentor_marks_an_item_done_with_a_note():
    table = Table([feedback("r1", NOW, question="q", answer="a")])
    item_id = f"{stamp(NOW)}#r1"
    response = lambda_handler(event("POST /review", body={"id": item_id, "status": "done", "note": " added eval case "}), None, deps(table))
    assert response["statusCode"] == 200
    saved = table.items[("FEEDBACK", item_id)]
    assert saved["review_status"] == "done" and saved["review_note"] == "added eval case" and saved["reviewed_by"] == "mentor@x.org"
    assert review.list_feedback(table, "down", "open", 90)["items"] == []

    missing = event("POST /review", body={"id": f"{stamp(NOW)}#gone", "status": "done"})
    assert lambda_handler(missing, None, deps(table))["statusCode"] == 404
    bad = event("POST /review", body={"id": "AUDIT#x", "status": "done"})
    assert lambda_handler(bad, None, deps(table))["statusCode"] == 400
    student = event("POST /review", "s@x.org", "student", body={"id": item_id, "status": "open"})
    assert lambda_handler(student, None, deps(table))["statusCode"] == 403


@pytest.mark.parametrize("status", ["", "closed", None])
def test_mark_rejects_unknown_statuses(status):
    with pytest.raises(ValueError):
        review.mark(Table(), f"{stamp(NOW)}#r1", status, "", "m", NOW)
