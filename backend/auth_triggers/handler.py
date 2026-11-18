"""Cognito triggers that enforce the team allowlist (DynamoDB items pk="ALLOW").

Entries are either an email (sk="alex@example.org") or a whole domain (sk="@example.org").
An email entry always wins, so one person in an allowed domain can be made a mentor or
blocked. Domain entries only match addresses Google reports as verified.

- Pre sign-up: a Google account not on the list never gets a user record.
- Pre token generation: runs on every sign-in *and* token refresh, so removing someone from the
  list locks them out within one token lifetime (1 hour). It also sets the `cognito:groups`
  claim to the allowlisted role, which the chat API checks.

Messages raised here are shown to the student on the sign-in page.
"""

import os
from functools import cache

ROLES = ("student", "mentor", "admin")
NOT_ALLOWED = "This Google account isn't on the team's access list. Ask a mentor to add you."


@cache
def _table():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def allowlisted_role(table, email: str, verified: bool = False) -> str | None:
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    role = _entry_role(table, email)
    if role is None and verified:
        role = _entry_role(table, "@" + email.rsplit("@", 1)[1])
    return role if role in ROLES else None  # "blocked" (or anything unknown) means no access


def _entry_role(table, key: str) -> str | None:
    item = table.get_item(Key={"pk": "ALLOW", "sk": key}, ConsistentRead=True).get("Item")
    return str(item.get("role") or "none") if item else None


def lambda_handler(event, context, table=None):
    table = table or _table()
    source = event["triggerSource"]
    attributes = event["request"]["userAttributes"]
    email = attributes.get("email", "")
    verified = str(attributes.get("email_verified", "")).lower() == "true"

    if source.startswith("PreSignUp"):
        if not allowlisted_role(table, email, verified):
            raise PermissionError(NOT_ALLOWED)
        return event

    if source.startswith("TokenGeneration"):
        role = allowlisted_role(table, email, verified)
        if not role:
            raise PermissionError(NOT_ALLOWED)
        event["response"]["claimsOverrideDetails"] = {"groupOverrideDetails": {"groupsToOverride": [role]}}
        return event

    return event
