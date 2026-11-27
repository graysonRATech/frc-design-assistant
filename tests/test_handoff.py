import json

from chat_api.handoff import HANDOFF_SECONDS, handler

STATE = "p." + "a" * 32


class Table:
    """Just enough of a DynamoDB table: conditional put, delete returning the old item."""

    class meta:
        class client:
            class exceptions:
                class ConditionalCheckFailedException(Exception):
                    pass

    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise self.meta.client.exceptions.ConditionalCheckFailedException()
        self.items[key] = Item

    def delete_item(self, Key, ReturnValues=None):
        old = self.items.pop((Key["pk"], Key["sk"]), None)
        return {"Attributes": old} if old else {}


def post(table, body, now=1000.0):
    event = {"requestContext": {"http": {"method": "POST"}}, "body": json.dumps(body)}
    return handler(event, None, table=table, now=now)


def get(table, state=STATE, now=1000.0):
    event = {"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": {"state": state}}
    return handler(event, None, table=table, now=now)


def test_code_is_handed_over_once():
    table = Table()
    assert post(table, {"state": STATE, "code": "c0de-1234-abcd"})["statusCode"] == 204
    first = get(table)
    assert first["statusCode"] == 200 and json.loads(first["body"]) == {"code": "c0de-1234-abcd"}
    assert get(table)["statusCode"] == 404  # deleted on read


def test_panel_polls_before_the_popup_is_done():
    assert get(Table())["statusCode"] == 404


def test_first_code_wins():
    table = Table()
    post(table, {"state": STATE, "code": "first-code-1"})
    post(table, {"state": STATE, "code": "second-code-2"})
    assert json.loads(get(table)["body"])["code"] == "first-code-1"


def test_expired_codes_are_not_handed_over():
    table = Table()
    post(table, {"state": STATE, "code": "c0de-1234-abcd"}, now=1000.0)
    assert get(table, now=1000.0 + HANDOFF_SECONDS + 1)["statusCode"] == 404


def test_only_panel_states_and_plain_codes_are_accepted():
    table = Table()
    for body in (
        {"state": "a" * 32, "code": "c0de-1234"},  # not a panel sign-in
        {"state": "p.short", "code": "c0de-1234"},
        {"state": STATE, "code": "<script>"},
        {"state": STATE},
    ):
        assert post(table, body)["statusCode"] == 400
    assert not table.items
    assert get(table, state="HANDOFF#x")["statusCode"] == 400
    bad = handler({"requestContext": {"http": {"method": "POST"}}, "body": "not json"}, None, table=table)
    assert bad["statusCode"] == 400


def test_responses_are_never_cached():
    assert get(Table())["headers"]["cache-control"] == "no-store"
