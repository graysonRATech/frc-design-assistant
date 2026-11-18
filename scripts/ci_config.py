"""Write config.local.yaml in GitHub Actions from repository variables and secrets.

config.local.yaml is gitignored (it holds the account ID and alert email), so the deploy workflow
rebuilds it from the environment. Anything not set here comes from config.example.yaml.

MODEL_CONFIG (optional repository variable) overrides keys of the `model` block as JSON, e.g.
{"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "endpoint": "runtime", "effort": "",
 "price_input_per_mtok": 1, "price_output_per_mtok": 5}
"""

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("AWS_ACCOUNT_ID", "ALERT_EMAIL", "GITHUB_REPOSITORY")
MODEL_KEYS = {"id", "endpoint", "max_tokens", "effort", "top_k", "price_input_per_mtok", "price_output_per_mtok"}


def build(env: dict[str, str]) -> dict:
    missing = [name for name in REQUIRED if not env.get(name, "").strip()]
    if missing:
        raise SystemExit(f"missing repository variables/secrets: {', '.join(missing)}")
    config = {
        "account": env["AWS_ACCOUNT_ID"].strip(),
        "alert_email": env["ALERT_EMAIL"].strip(),
        "web": {
            "google_client_id": env.get("GOOGLE_CLIENT_ID", "").strip(),
            # Optional custom domain (README "Custom domain"); the ARN names the account, so it's a secret.
            "domain_name": env.get("DOMAIN_NAME", "").strip(),
            "certificate_arn": env.get("CERTIFICATE_ARN", "").strip(),
        },
        # The repo running the workflow, so the OIDC trust always matches where deploys come from.
        "github": {"repo": env["GITHUB_REPOSITORY"].strip()},
    }
    if model := _model(env.get("MODEL_CONFIG", "")):
        config["model"] = model
    return config


def _model(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        model = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SystemExit(f"MODEL_CONFIG is not valid JSON: {error}") from None
    if not isinstance(model, dict) or not set(model) <= MODEL_KEYS:
        raise SystemExit(f"MODEL_CONFIG must be a JSON object with keys from: {', '.join(sorted(MODEL_KEYS))}")
    return model


def main() -> int:
    path = ROOT / "config.local.yaml"
    path.write_text(yaml.safe_dump(build(dict(os.environ)), sort_keys=False), encoding="utf-8")
    print(f"wrote {path.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
