import pytest
import yaml

from infra.config import load
from scripts.ci_config import build


def test_build_maps_environment_to_config(tmp_path):
    data = build(
        {"AWS_ACCOUNT_ID": "111122223333 ", "ALERT_EMAIL": "coach@example.org", "GOOGLE_CLIENT_ID": "abc", "GITHUB_REPOSITORY": "team/rag"}
    )
    local = tmp_path / "config.local.yaml"
    local.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load(local)
    assert (config.account, config.alert_email, config.google_client_id, config.github_repo) == (
        "111122223333",
        "coach@example.org",
        "abc",
        "team/rag",
    )


def test_build_names_missing_settings():
    with pytest.raises(SystemExit, match="ALERT_EMAIL"):
        build({"AWS_ACCOUNT_ID": "111122223333", "GITHUB_REPOSITORY": "team/rag"})


BASE = {"AWS_ACCOUNT_ID": "111122223333", "ALERT_EMAIL": "coach@example.org", "GITHUB_REPOSITORY": "team/rag"}


def test_model_config_overrides_the_model_block(tmp_path):
    model = '{"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "endpoint": "runtime", "effort": "", "price_input_per_mtok": 1}'
    local = tmp_path / "config.local.yaml"
    local.write_text(yaml.safe_dump(build({**BASE, "MODEL_CONFIG": model})), encoding="utf-8")
    config = load(local)
    assert (config.model_id, config.model_endpoint, config.effort, config.price_input_per_mtok) == (
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "runtime",
        "",
        1.0,
    )


@pytest.mark.parametrize("raw", ["not json", "[1]", '{"modle": "x"}'])
def test_model_config_rejects_bad_values(raw):
    with pytest.raises(SystemExit, match="MODEL_CONFIG"):
        build({**BASE, "MODEL_CONFIG": raw})


def test_custom_domain_comes_from_environment(tmp_path):
    cert = "arn:aws:acm:us-east-1:111122223333:certificate/abc"
    local = tmp_path / "config.local.yaml"
    local.write_text(yaml.safe_dump(build({**BASE, "DOMAIN_NAME": "frc.example.org", "CERTIFICATE_ARN": cert})), encoding="utf-8")
    config = load(local)
    assert (config.domain_name, config.certificate_arn) == ("frc.example.org", cert)
