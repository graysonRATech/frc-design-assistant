"""Sign-in handoff for the Onshape panel.

The panel is our page inside an Onshape iframe, where Google won't show its sign-in page. So the
panel opens a popup that signs in on our site and lands on /onshape/index.html with an OAuth
authorization code. The popup can usually hand the code straight back with postMessage, but
Google's sign-in pages often cut the popup off from the page that opened it. As a fallback the
popup leaves the code here, keyed by the OAuth `state` only the panel knows, and the panel picks
it up (once) by polling.

What's stored is safe to hold briefly: an authorization code is single use, expires in minutes,
and can't be exchanged without the PKCE code verifier, which never leaves the panel. Records
expire after HANDOFF_SECONDS and are deleted when read.

    POST {"state": "...", "code": "..."}   -> 204 (the popup)
    GET  ?state=...                        -> 200 {"code": "..."} once, else 404 (the panel)
"""

import json
import os
import re
import time

import boto3

HANDOFF_SECONDS = 300
_STATE = re.compile(r"^p\.[A-Za-z0-9_-]{20,64}$")  # "p." marks a popup sign-in (see web/src/lib/auth.js)
_CODE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def handler(event, context, table=None, now=None):
    table = table or boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    now = now or time.time()
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except ValueError:
            return _reply(400, {"error": "bad request"})
        state, code = str(body.get("state", "")), str(body.get("code", ""))
        if not _STATE.match(state) or not _CODE.match(code):
            return _reply(400, {"error": "bad request"})
        try:
            table.put_item(
                Item={"pk": f"HANDOFF#{state}", "sk": "code", "code": code, "expires_at": int(now) + HANDOFF_SECONDS},
                ConditionExpression="attribute_not_exists(pk)",  # first write wins; no overwrites
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass
        return _reply(204)
    if method == "GET":
        state = str((event.get("queryStringParameters") or {}).get("state", ""))
        if not _STATE.match(state):
            return _reply(400, {"error": "bad request"})
        item = table.delete_item(Key={"pk": f"HANDOFF#{state}", "sk": "code"}, ReturnValues="ALL_OLD").get("Attributes")
        if not item or int(item.get("expires_at", 0)) < now:
            return _reply(404, {"error": "not yet"})
        return _reply(200, {"code": item["code"]})
    return _reply(405, {"error": "method not allowed"})


def _reply(status: int, body: dict | None = None) -> dict:
    reply = {"statusCode": status, "headers": {"cache-control": "no-store"}}
    if body is not None:
        reply["headers"]["content-type"] = "application/json"
        reply["body"] = json.dumps(body)
    return reply
