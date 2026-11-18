import pytest

from auth_triggers.handler import NOT_ALLOWED, lambda_handler


class AllowTable:
    def __init__(self, entries: dict[str, str]):
        self.entries = entries

    def get_item(self, Key, ConsistentRead=False):
        assert Key["pk"] == "ALLOW"
        role = self.entries.get(Key["sk"])
        return {"Item": {"pk": "ALLOW", "sk": Key["sk"], "role": role}} if role else {}


TABLE = AllowTable(
    {
        "student@example.org": "student",
        "coach@example.org": "admin",
        "old@example.org": "bogus",
        "@school.org": "student",
        "teacher@school.org": "mentor",
        "expelled@school.org": "blocked",
    }
)


def event(source: str, email: str, verified: str | None = None) -> dict:
    attributes = {"email": email} | ({"email_verified": verified} if verified is not None else {})
    return {"triggerSource": source, "request": {"userAttributes": attributes}, "response": {}}


def groups(result) -> list[str]:
    return result["response"]["claimsOverrideDetails"]["groupOverrideDetails"]["groupsToOverride"]


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


def test_domain_entry_allows_verified_addresses_as_students():
    assert lambda_handler(event("PreSignUp_ExternalProvider", "New.Kid@School.org", "true"), None, TABLE)
    assert groups(lambda_handler(event("TokenGeneration_HostedAuth", "new.kid@school.org", "true"), None, TABLE)) == ["student"]


@pytest.mark.parametrize("verified", [None, "false"])
def test_domain_entry_ignores_unverified_addresses(verified):
    with pytest.raises(PermissionError, match=NOT_ALLOWED):
        lambda_handler(event("PreSignUp_ExternalProvider", "new.kid@school.org", verified), None, TABLE)


def test_email_entry_overrides_domain_entry():
    assert groups(lambda_handler(event("TokenGeneration_HostedAuth", "teacher@school.org", "true"), None, TABLE)) == ["mentor"]
    with pytest.raises(PermissionError):
        lambda_handler(event("TokenGeneration_RefreshTokens", "expelled@school.org", "true"), None, TABLE)


@pytest.mark.parametrize("email", ["x@evilschool.org", "x@sub.school.org"])
def test_domain_entry_does_not_match_lookalike_domains(email):
    with pytest.raises(PermissionError):
        lambda_handler(event("PreSignUp_ExternalProvider", email, "true"), None, TABLE)
