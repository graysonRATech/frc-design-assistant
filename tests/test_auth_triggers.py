import pytest

from auth_triggers.handler import NOT_ALLOWED, lambda_handler


class AllowTable:
    def __init__(self, entries: dict[str, str]):
        self.entries = entries

    def get_item(self, Key, ConsistentRead=False):
        assert Key["pk"] == "ALLOW"
        role = self.entries.get(Key["sk"])
        return {"Item": {"pk": "ALLOW", "sk": Key["sk"], "role": role}} if role else {}


TABLE = AllowTable({"student@example.org": "student", "coach@example.org": "admin", "old@example.org": "bogus"})


def event(source: str, email: str) -> dict:
    return {"triggerSource": source, "request": {"userAttributes": {"email": email}}, "response": {}}


def test_pre_sign_up_allows_listed_emails_case_insensitively():
    assert lambda_handler(event("PreSignUp_ExternalProvider", "Student@Example.org"), None, TABLE)


@pytest.mark.parametrize("email", ["stranger@example.org", "", "old@example.org"])
def test_pre_sign_up_rejects_everyone_else(email):
    with pytest.raises(PermissionError, match=NOT_ALLOWED):
        lambda_handler(event("PreSignUp_ExternalProvider", email), None, TABLE)


def test_token_generation_sets_role_group():
    result = lambda_handler(event("TokenGeneration_RefreshTokens", "coach@example.org"), None, TABLE)
    assert result["response"]["claimsOverrideDetails"]["groupOverrideDetails"]["groupsToOverride"] == ["admin"]


def test_token_generation_blocks_removed_users():
    with pytest.raises(PermissionError):
        lambda_handler(event("TokenGeneration_HostedAuth", "stranger@example.org"), None, TABLE)
