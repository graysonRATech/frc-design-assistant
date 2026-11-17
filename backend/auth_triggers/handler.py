"""Cognito triggers that enforce the team allowlist (DynamoDB items pk="ALLOW", sk=<email>).

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


def allowlisted_role(table, email: str) -> str | None:
    if not email:
        return None
    item = table.get_item(Key={"pk": "ALLOW", "sk": email.strip().lower()}, ConsistentRead=True).get("Item")
    role = item.get("role") if item else None
    return role if role in ROLES else None


def lambda_handler(event, context, table=None):
    table = table or _table()
    source = event["triggerSource"]
    email = event["request"]["userAttributes"].get("email", "")

    if source.startswith("PreSignUp"):
        if not allowlisted_role(table, email):
            raise PermissionError(NOT_ALLOWED)
        return event

    if source.startswith("TokenGeneration"):
        role = allowlisted_role(table, email)
        if not role:
            raise PermissionError(NOT_ALLOWED)
        event["response"]["claimsOverrideDetails"] = {"groupOverrideDetails": {"groupsToOverride": [role]}}
        return event

    return event
