"""Deploy settings from config.local.yaml, with defaults from config.example.yaml."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DeployConfig:
    account: str
    region: str
    stack_name: str
    monthly_budget_usd: float
    alert_email: str
    user_daily_usd: float
    monthly_usd: float
    model_id: str
    model_endpoint: str
    max_tokens: int
    effort: str
    top_k: int
    price_input_per_mtok: float
    price_output_per_mtok: float
    lambda_reserved_concurrency: int
    audit_retention_days: int
    google_client_id: str
    google_secret_name: str
    auth_domain_prefix: str
    extra_web_origins: tuple[str, ...]
    domain_name: str
    certificate_arn: str
    api_rate_per_second: float
    api_burst: int
    github_repo: str

    @property
    def extra_web_origins_slash(self) -> list[str]:
        return [origin.rstrip("/") + "/" for origin in self.extra_web_origins]


def load(path: Path | None = None) -> DeployConfig:
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    local = path or ROOT / "config.local.yaml"
    if local.exists():
        _merge(data, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    limits, model, web = data["limits"], data["model"], data["web"]
    if limits["monthly_usd"] >= data["monthly_budget_usd"]:
        raise ValueError("limits.monthly_usd must be below monthly_budget_usd")
    return DeployConfig(
        account=str(data["account"]),
        region=data["region"],
        stack_name=data["stack_name"],
        monthly_budget_usd=float(data["monthly_budget_usd"]),
        alert_email=data["alert_email"],
        user_daily_usd=float(limits["user_daily_usd"]),
        monthly_usd=float(limits["monthly_usd"]),
        model_id=model["id"],
        model_endpoint=_endpoint(model.get("endpoint", "mantle")),
        max_tokens=int(model["max_tokens"]),
        effort=str(model["effort"] or ""),
        top_k=int(model["top_k"]),
        price_input_per_mtok=float(model["price_input_per_mtok"]),
        price_output_per_mtok=float(model["price_output_per_mtok"]),
        lambda_reserved_concurrency=int(data["lambda_reserved_concurrency"]),
        audit_retention_days=int(data["audit_retention_days"]),
        google_client_id=str(web["google_client_id"] or ""),
        google_secret_name=web["google_secret_name"],
        auth_domain_prefix=web["auth_domain_prefix"] or f"frc-rag-{data['account']}",
        extra_web_origins=tuple(o.rstrip("/") for o in web["extra_origins"] or []),
        **_custom_domain(web.get("domain_name"), web.get("certificate_arn")),
        api_rate_per_second=float(web["api_rate_per_second"]),
        api_burst=int(web["api_burst"]),
        github_repo=_github_repo(data["github"]["repo"]),
    )


def _endpoint(value: str) -> str:
    if value not in ("mantle", "runtime"):
        raise ValueError("model.endpoint must be 'mantle' or 'runtime'")
    return value


def _custom_domain(name, certificate_arn) -> dict:
    name, certificate_arn = str(name or "").strip().lower(), str(certificate_arn or "").strip()
    if bool(name) != bool(certificate_arn):
        raise ValueError("web.domain_name and web.certificate_arn must be set together")
    if name and not re.fullmatch(r"([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", name):
        raise ValueError(f"web.domain_name must be a host name like frc.example.org, got {name!r}")
    # CloudFront only accepts certificates from us-east-1, whatever region the stack is in.
    if certificate_arn and not certificate_arn.startswith("arn:aws:acm:us-east-1:"):
        raise ValueError("web.certificate_arn must be an ACM certificate in us-east-1")
    return {"domain_name": name, "certificate_arn": certificate_arn}


def _github_repo(value) -> str:
    repo = str(value or "").strip()
    if repo and not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", repo):
        raise ValueError(f"github.repo must look like owner/name, got {repo!r}")
    return repo


def _merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
