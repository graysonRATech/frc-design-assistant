"""Loading and validating sources.yaml."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SOURCE_TYPES = {
    "game_manual": ("url", "year"),
    "github_repo": ("repo", "base_url"),
    "sitemap": ("url",),
}
LICENSE_STATUSES = ("attributed", "permitted", "link-only")
REFRESH_CADENCES = ("daily", "weekly", "monthly", "manual")

_COMMON_KEYS = {"id", "type", "name", "attribution", "license_status", "refresh"}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SourceConfig:
    id: str
    type: str
    name: str
    attribution: str
    license_status: str
    refresh: str
    options: dict = field(default_factory=dict)


def load_sources(path: Path) -> list[SourceConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = data.get("sources") or []
    if not isinstance(entries, list):
        raise ConfigError("'sources' must be a list")

    sources: list[SourceConfig] = []
    seen: set[str] = set()
    for entry in entries:
        sources.append(_parse_source(entry, seen))
    return sources


def _parse_source(entry: object, seen: set[str]) -> SourceConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"source entries must be mappings, got {entry!r}")

    source_id = entry.get("id")
    if not isinstance(source_id, str) or not _ID.match(source_id):
        raise ConfigError(f"invalid source id {source_id!r}: use lowercase letters, digits and dashes")
    if source_id in seen:
        raise ConfigError(f"duplicate source id {source_id!r}")
    seen.add(source_id)

    source_type = entry.get("type")
    if source_type not in SOURCE_TYPES:
        raise ConfigError(f"{source_id}: unknown type {source_type!r}; expected one of {sorted(SOURCE_TYPES)}")
    missing = [key for key in SOURCE_TYPES[source_type] if not entry.get(key)]
    if missing:
        raise ConfigError(f"{source_id}: {source_type} sources require {', '.join(missing)}")

    license_status = entry.get("license_status", "attributed")
    if license_status not in LICENSE_STATUSES:
        raise ConfigError(f"{source_id}: license_status must be one of {LICENSE_STATUSES}")
    refresh = entry.get("refresh", "manual")
    if refresh not in REFRESH_CADENCES:
        raise ConfigError(f"{source_id}: refresh must be one of {REFRESH_CADENCES}")

    return SourceConfig(
        id=source_id,
        type=source_type,
        name=entry.get("name", source_id),
        attribution=entry.get("attribution", entry.get("name", source_id)),
        license_status=license_status,
        refresh=refresh,
        options={k: v for k, v in entry.items() if k not in _COMMON_KEYS},
    )
