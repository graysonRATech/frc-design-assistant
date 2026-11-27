"""Mentor review of answer feedback: thumbs-down (and up) ratings with the answer they rate.

Feedback items live under pk = "FEEDBACK", sk = "<time>#<request id>" (see handler._feedback).
When a student rates an answer, the question, answer and sources are copied from that answer's
audit record into the feedback item, so the review list is a single query. Older feedback, saved
before the copy existed, is looked up at review time instead.

A mentor marks an item "done" (optionally with a note, e.g. "added eval case bumper-foam") so the
list only shows what still needs a look.
"""

from datetime import datetime, timedelta

from .conversations import plain

STATUSES = ("open", "done")
RATINGS = ("down", "up", "all")
MAX_NOTE_CHARS = 500
PAGE_SIZE = 25
ANSWER_FIELDS = ("question", "answer", "sources", "cited", "retrieved", "model", "chat_id", "outcome")


def find_answer(table, user: str, request_id: str, before: datetime, window_days: int) -> dict:
    """The audit record of `user`'s answer `request_id`, from the `window_days` before `before`."""
    from boto3.dynamodb.conditions import Attr, Key

    start = (before - timedelta(days=window_days)).isoformat(timespec="milliseconds")
    end = before.isoformat(timespec="milliseconds") + "~"
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(f"AUDIT#{user}") & Key("sk").between(start, end),
        "FilterExpression": Attr("request_id").eq(request_id),
        "ScanIndexForward": False,
    }
    while True:
        page = table.query(**kwargs)
        if page["Items"]:
            return page["Items"][0]
        if "LastEvaluatedKey" not in page:
            return {}
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def answer_fields(audit_item: dict) -> dict:
    return {name: audit_item[name] for name in ANSWER_FIELDS if name in audit_item}


def list_feedback(table, rating: str, status: str, window_days: int, cursor: str | None = None) -> dict:
    """Newest first, up to PAGE_SIZE matching items, and a cursor for the next page (or None)."""
    from boto3.dynamodb.conditions import Attr, Key

    if rating not in RATINGS:
        raise ValueError(f"'rating' must be one of {', '.join(RATINGS)}")
    if status not in (*STATUSES, "all"):
        raise ValueError("'status' must be open, done or all")
    condition = None
    if rating != "all":
        condition = Attr("rating").eq(rating)
    if status == "open":
        open_ = Attr("review_status").not_exists() | Attr("review_status").eq("open")
        condition = open_ if condition is None else condition & open_
    elif status == "done":
        done = Attr("review_status").eq("done")
        condition = done if condition is None else condition & done

    kwargs = {"KeyConditionExpression": Key("pk").eq("FEEDBACK"), "ScanIndexForward": False, "Limit": 100}
    if condition is not None:
        kwargs["FilterExpression"] = condition
    if cursor:
        kwargs["ExclusiveStartKey"] = {"pk": "FEEDBACK", "sk": cursor}

    items, next_cursor = [], None
    while True:
        page = table.query(**kwargs)
        for item in page["Items"]:
            items.append(item)
            if len(items) == PAGE_SIZE:
                next_cursor = item["sk"]
                break
        if next_cursor or "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return {"items": [_view(table, item, window_days) for item in items], "next": next_cursor}


def _view(table, item: dict, window_days: int) -> dict:
    if "question" not in item and item.get("user") and item.get("request_id"):
        rated_at = _time_of(item["sk"])
        if rated_at:
            item = {**answer_fields(find_answer(table, item["user"], item["request_id"], rated_at, window_days)), **item}
    sources = item.get("sources") or [{"number": i + 1, "title": "", "url": url} for i, url in enumerate(item.get("cited", []))]
    return plain(
        {
            "id": item["sk"],
            "rated_at": item["sk"].split("#", 1)[0],
            "rating": item.get("rating"),
            "comment": item.get("comment", ""),
            "user": item.get("user", ""),
            "request_id": item.get("request_id", ""),
            "question": item.get("question"),
            "answer": item.get("answer"),
            "sources": sources,
            "retrieved": item.get("retrieved", []),
            "model": item.get("model", ""),
            "outcome": item.get("outcome", ""),
            "status": item.get("review_status", "open"),
            "note": item.get("review_note", ""),
            "reviewed_by": item.get("reviewed_by", ""),
            "reviewed_at": item.get("reviewed_at", ""),
        }
    )


def mark(table, item_id: str, status: str, note: str, reviewer: str, now: datetime) -> dict:
    if status not in STATUSES:
        raise ValueError("'status' must be open or done")
    if not isinstance(item_id, str) or not _time_of(item_id):
        raise ValueError("'id' must be a feedback id")
    if not isinstance(note, str):
        raise ValueError("'note' must be a string")
    try:
        table.update_item(
            Key={"pk": "FEEDBACK", "sk": item_id},
            UpdateExpression="SET review_status = :s, review_note = :n, reviewed_by = :r, reviewed_at = :t",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={
                ":s": status,
                ":n": note.strip()[:MAX_NOTE_CHARS],
                ":r": reviewer,
                ":t": now.isoformat(timespec="seconds"),
            },
        )
    except Exception as error:  # botocore ClientError, without importing botocore here
        if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise LookupError(item_id) from error
        raise
    return {"id": item_id, "status": status, "note": note.strip()[:MAX_NOTE_CHARS], "reviewed_by": reviewer}


def _time_of(sk: str) -> datetime | None:
    try:
        return datetime.fromisoformat(sk.split("#", 1)[0])
    except ValueError:
        return None
