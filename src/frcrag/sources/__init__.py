"""Source fetchers: each turns a sources.yaml entry into normalized Documents."""

from collections.abc import Callable
from pathlib import Path

from ..config import SourceConfig
from . import game_manual, github_repo, sitemap
from .base import Document, FetchResult

FETCHERS: dict[str, Callable[[SourceConfig, Path], FetchResult]] = {
    "game_manual": game_manual.fetch,
    "github_repo": github_repo.fetch,
    "sitemap": sitemap.fetch,
}


def fetch(source: SourceConfig, cache_dir: Path) -> FetchResult:
    return FETCHERS[source.type](source, cache_dir)


__all__ = ["Document", "FetchResult", "fetch"]
