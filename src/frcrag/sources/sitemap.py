"""Ingest rendered pages listed in a sitemap (for sites without a public source repo)."""

import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from .. import http
from ..config import SourceConfig
from ..normalize.html import html_to_markdown
from .base import Document, FetchResult, path_matches

log = logging.getLogger(__name__)

_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def fetch(source: SourceConfig, cache_dir: Path) -> FetchResult:
    opts = source.options
    include = opts.get("include") or ["*"]
    exclude = opts.get("exclude") or []
    max_pages = int(opts.get("max_pages", 500))
    delay = float(opts.get("delay_seconds", 1.0))

    urls = sorted({u for u in list_sitemap_urls(opts["url"]) if path_matches(urlparse(u).path, include, exclude)})
    if len(urls) > max_pages:
        log.warning("%s: %d pages match; only the first %d will be fetched", source.id, len(urls), max_pages)
        urls = urls[:max_pages]

    documents: list[Document] = []
    digest = hashlib.sha256()
    for i, url in enumerate(urls):
        if i:
            time.sleep(delay)
        try:
            html = http.get(url).decode("utf-8", errors="replace")
        except Exception as error:  # one bad page shouldn't sink the whole source
            log.warning("%s: skipping %s (%s)", source.id, url, error)
            continue
        title, markdown = html_to_markdown(html, url)
        digest.update(url.encode() + b"\0" + markdown.encode())
        slug = urlparse(url).path.strip("/")
        documents.append(
            Document(
                source_id=source.id,
                doc_id=slug or "index",
                url=url,
                title=title,
                section=slug.split("/", 1)[0],
                markdown=markdown,
            )
        )
    return FetchResult(documents=documents, revision=f"sha256:{digest.hexdigest()[:16]}")


def list_sitemap_urls(sitemap_url: str, _depth: int = 0) -> list[str]:
    """Page URLs from a sitemap or sitemap index, restricted to the sitemap's own host."""
    host = urlparse(sitemap_url).hostname
    root = ElementTree.fromstring(http.get(sitemap_url))
    locations = [loc.text.strip() for loc in root.iter(f"{_NS}loc") if loc.text]
    locations = [u for u in locations if urlparse(u).hostname == host]

    if root.tag != f"{_NS}sitemapindex":
        return locations
    if _depth >= 2:
        return []
    return [url for child in locations for url in list_sitemap_urls(child, _depth + 1)]
