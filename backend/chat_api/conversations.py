"""Saved chats, one DynamoDB item per conversation in the app table.

    pk = "CHATS#<user>", sk = <chat id>   title, created_at, updated_at, expires_at, messages[]
    pk = "STOP#<user>",  sk = <request id> a "stop generating" request from the browser

A chat expires `retention_days` after its last message (DynamoDB TTL), and students can delete
their own chats at any time. Each message is {role, content}, plus for answers the cited
`sources`, the `request_id` (for feedback) and `stopped` if the student stopped it early.
"""

import json
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

MAX_TURNS = 30  # question/answer pairs per chat
MAX_ITEM_BYTES = 350_000  # DynamoDB items are capped at 400 KB
TITLE_CHARS = 80
_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{8}$")


class ChatNotFound(Exception):
    pass


class ChatFull(Exception):
    pass


def new_chat_id(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"


def title_from(question: str) -> str:
    line = " ".join(question.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


def plain(value):
    """DynamoDB returns numbers as Decimal; turn an item back into JSON-safe values."""
    return json.loads(json.dumps(value, default=lambda d: int(d) if d == int(d) else float(d)))


class Conversations:
    def __init__(self, table, retention_days: int):
        self.table = table
        self.retention_days = retention_days

    @staticmethod
    def _key(user: str, chat_id: str) -> dict:
        if not isinstance(chat_id, str) or not _ID.match(chat_id):
            raise ChatNotFound(chat_id)
        return {"pk": f"CHATS#{user}", "sk": chat_id}

    def list(self, user: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        kwargs = {
            "KeyConditionExpression": Key("pk").eq(f"CHATS#{user}"),
            "ProjectionExpression": "sk, #t, updated_at",
            "ExpressionAttributeNames": {"#t": "title"},
        }
        chats = []
        while True:
            page = self.table.query(**kwargs)
            chats += [{"id": i["sk"], "title": i.get("title", ""), "updated_at": i.get("updated_at", "")} for i in page["Items"]]
            if "LastEvaluatedKey" not in page:
                return sorted(chats, key=lambda c: c["updated_at"], reverse=True)
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def get(self, user: str, chat_id: str) -> dict:
        item = self.table.get_item(Key=self._key(user, chat_id), ConsistentRead=True).get("Item")
        if not item:
            raise ChatNotFound(chat_id)
        return {
            "id": item["sk"],
            "title": item.get("title", ""),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "messages": plain(item.get("messages", [])),
        }

    def save(self, user: str, chat: dict, now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        item = {
            **self._key(user, chat["id"]),
            "title": chat["title"],
            "created_at": chat.get("created_at") or stamp,
            "updated_at": stamp,
            "expires_at": int((now + timedelta(days=self.retention_days)).timestamp()),
            "messages": chat["messages"],
        }
        encoded = json.dumps(item)
        if len(encoded.encode()) > MAX_ITEM_BYTES:
            raise ChatFull(chat["id"])
        self.table.put_item(Item=json.loads(encoded, parse_float=Decimal))

    def rename(self, user: str, chat_id: str, title: str) -> str:
        title = title_from(title)
        if not title:
            raise ValueError("'title' can't be empty")
        try:
            self.table.update_item(
                Key=self._key(user, chat_id),
                UpdateExpression="SET #t = :t",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeNames={"#t": "title"},
                ExpressionAttributeValues={":t": title},
            )
        except Exception as error:  # botocore ClientError, without importing botocore here
            if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ChatNotFound(chat_id) from error
            raise
        return title

    def delete(self, user: str, chat_id: str) -> None:
        self.table.delete_item(Key=self._key(user, chat_id))

    def request_stop(self, user: str, request_id: str, now: datetime) -> None:
        self.table.put_item(
            Item={"pk": f"STOP#{user}", "sk": request_id[:64], "expires_at": int((now + timedelta(days=1)).timestamp())}
        )

    def stop_requested(self, user: str, request_id: str) -> bool:
        return "Item" in self.table.get_item(Key={"pk": f"STOP#{user}", "sk": request_id[:64]}, ConsistentRead=True)
