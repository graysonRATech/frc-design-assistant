"""Ingest Markdown/MDX docs straight from a GitHub repository snapshot.

Reading the source files gives cleaner text than crawling the rendered site (no navigation
or sponsor boilerplate) and pins every build to an exact commit.
"""

import io
import logging
import re
import shutil
import tarfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .. import http
from ..config import SourceConfig
from ..normalize.common import humanize
from ..normalize.mdx import mdx_to_markdown, split_frontmatter
from .base import Document, FetchResult, path_matches

log = logging.getLogger(__name__)

DOC_SUFFIXES = (".md", ".mdx")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def fetch(source: SourceConfig, cache_dir: Path) -> FetchResult:
    opts = source.options
    repo, ref = opts["repo"], opts.get("ref", "main")
    root = str(opts.get("path", "")).strip("/")

    sha = resolve_commit(repo, ref)
    log.info("%s: %s@%s resolved to %s", source.id, repo, ref, sha[:12])
    snapshot = download_snapshot(repo, sha, root, cache_dir / source.id / sha)
    docs_root = snapshot / root if root else snapshot
    return FetchResult(documents=list(collect_documents(docs_root, source)), revision=f"{repo}@{sha}")


def resolve_commit(repo: str, ref: str) -> str:
    sha = http.get(
        f"https://api.github.com/repos/{repo}/commits/{quote(ref, safe='')}",
        accept="application/vnd.github.sha",
    ).decode().strip()
    if not _SHA.match(sha):
        raise RuntimeError(f"unexpected commit id for {repo}@{ref}: {sha[:80]!r}")
    return sha


def download_snapshot(repo: str, sha: str, root: str, dest: Path) -> Path:
    """Extract only the doc files under `root` from the commit tarball; cached per commit."""
    marker = dest / ".complete"
    if marker.exists():
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    data = http.get(f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=120)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = []
        for member in tar.getmembers():
            _, _, rel = member.name.partition("/")  # drop the "<repo>-<sha>/" top-level folder
            if not member.isfile() or not rel.endswith(DOC_SUFFIXES):
                continue
            if root and not rel.startswith(root + "/"):
                continue
            member.name = rel
            members.append(member)
        # The "data" filter rejects absolute paths, links and traversal outside dest.
        tar.extractall(dest, members=members, filter="data")
    marker.touch()
    return dest


def collect_documents(docs_root: Path, source: SourceConfig) -> Iterator[Document]:
    include = source.options.get("include") or ["*"]
    exclude = source.options.get("exclude") or []
    base_url = source.options["base_url"]

    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.suffix not in DOC_SUFFIXES:
            continue
        rel = path.relative_to(docs_root).as_posix()
        if not path_matches(rel, include, exclude):
            continue

        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if frontmatter.get("draft"):
            continue

        slug = page_slug(rel)
        url = page_url(base_url, slug)
        yield Document(
            source_id=source.id,
            doc_id=slug or "index",
            url=url,
            title=str(frontmatter.get("title") or humanize(PurePosixPath(slug).name) or source.name),
            section=slug.split("/", 1)[0],
            markdown=mdx_to_markdown(body, url),
            description=str(frontmatter.get("description") or ""),
        )


def page_slug(rel_path: str) -> str:
    """'learning-course/stage1/index.mdx' -> 'learning-course/stage1' (Starlight routing)."""
    parts = list(PurePosixPath(rel_path).with_suffix("").parts)
    if parts and parts[-1] == "index":
        parts.pop()
    return "/".join(parts)


def page_url(base_url: str, slug: str) -> str:
    base = base_url.rstrip("/") + "/"
    return f"{base}{quote(slug)}/" if slug else base
