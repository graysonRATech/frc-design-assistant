"""Past seasons' games, from FIRST's PDF game manuals: the overview, field and match chapters only.

On kickoff day students want to spot what the new game shares with old ones ("a hub you shoot
into, like 2022"). These chapters describe each game, its field, game pieces and scoring. The
rules chapters are left out on purpose: old rules often share numbers with current ones and
would be cited as if they still applied.

Each numbered subsection (from the PDF's bookmarks) becomes a document titled "Past game: 2022
RAPID REACT, 5.3 Hub", linked to its page. sources.yaml lists, per game, which chapters to keep,
because chapter names vary by year (2018 called its field chapter "ARCADE").
"""

import hashlib
import io
import logging
import re
from pathlib import Path

from pypdf import PdfReader

from .. import http
from ..config import SourceConfig
from .base import Document, FetchResult

log = logging.getLogger(__name__)

_PAGE_FOOTER = re.compile(r"\d+\s+of\s+\d+\s*$")
_BULLET = re.compile(r"^[•▪●]\s*")
_SPACES = re.compile(r"[ \t]{2,}")


def fetch(source: SourceConfig, cache_dir: Path) -> FetchResult:
    documents: list[Document] = []
    digest = hashlib.sha256()
    games = source.options["games"]
    for game in games:
        raw = _download(game["url"], cache_dir / source.id)
        digest.update(raw)
        docs = game_documents(PdfReader(io.BytesIO(raw)), game, source.id)
        log.info("%s: %d %s, %d sections", source.id, game["year"], game["name"], len(docs))
        documents.extend(docs)
    documents.extend(summary_documents(games, source.id, source.options.get("index_url", "")))
    return FetchResult(documents=documents, revision=f"{len(source.options['games'])} manuals sha256:{digest.hexdigest()[:16]}")


def summary_documents(games: list[dict], source_id: str, index_url: str) -> list[Document]:
    """One "at a glance" document per game, plus one listing every game.

    Questions like "which games had a hub you shoot into?" span seasons; matching them against
    one season's field chapter at a time ranks poorly. The combined list puts every season's game
    pieces, goals and endgame in a single excerpt. Summaries are written by hand in sources.yaml
    from each manual's overview and game piece sections.
    """
    games = [g for g in games if g.get("summary")]
    documents = [
        Document(
            source_id=source_id,
            doc_id=f"{g['year']}/at-a-glance",
            url=str(g["url"]),
            title=f"Past game: {g['year']} {g['name']} at a glance",
            section=f"{g['year']}-{_slug(str(g['name']))}",
            markdown=_summary(g) + "\n",
            description=f"{g['year']} {g['name']}",
        )
        for g in games
    ]
    if games and index_url:
        years = sorted(int(g["year"]) for g in games)
        documents.append(
            Document(
                source_id=source_id,
                doc_id="at-a-glance",
                url=index_url,
                title=f"Past FRC games at a glance, {years[0]}-{years[-1]}",
                section="past-games",
                markdown="\n\n".join(f"**{g['year']} {g['name']}**: {_summary(g)}" for g in sorted(games, key=lambda g: -int(g["year"]))) + "\n",
            )
        )
    return documents


def _summary(game: dict) -> str:
    return " ".join(str(game["summary"]).split())


def _download(url: str, cache: Path) -> bytes:
    """Past manuals don't change, so keep a copy between runs on the same machine."""
    path = cache / hashlib.sha256(url.encode()).hexdigest()[:16]
    if path.exists():
        return path.read_bytes()
    raw = http.get(url, timeout=120)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def game_documents(reader: PdfReader, game: dict, source_id: str) -> list[Document]:
    year, name, url = int(game["year"]), str(game["name"]), str(game["url"])
    wanted = {str(c) for c in game["chapters"]}
    entries = _outline_entries(reader)  # (depth, title, page index), in reading order
    documents: list[Document] = []
    for i, (depth, title, page) in enumerate(entries):
        chapter = title.split(" ", 1)[0].split(".", 1)[0]
        if chapter not in wanted:
            continue
        following = entries[i + 1] if i + 1 < len(entries) else None
        last_page = following[2] if following else len(reader.pages) - 1
        text = _section_text(reader, page, last_page, title, following[1] if following else None)
        if not text:
            continue
        documents.append(
            Document(
                source_id=source_id,
                doc_id=f"{year}/{_slug(title)}",
                url=f"{url}#page={page + 1}",
                title=f"Past game: {year} {name}, {title}",
                section=f"{year}-{_slug(name)}",
                markdown=text,
                description=f"{year} {name}",
            )
        )
    return documents


def _outline_entries(reader: PdfReader) -> list[tuple[int, str, int]]:
    entries: list[tuple[int, str, int]] = []

    def walk(items, depth):
        for item in items:
            if isinstance(item, list):
                if depth < 1:  # chapters and their numbered sections; deeper levels stay inside
                    walk(item, depth + 1)
                continue
            try:
                entries.append((depth, re.sub(r"\s+", " ", item.title).strip(), reader.get_destination_page_number(item)))
            except Exception:  # a bookmark without a page
                continue

    walk(reader.outline, 0)
    return entries


def _section_text(reader: PdfReader, first: int, last: int, title: str, next_title: str | None) -> str:
    """Text from this bookmark's heading up to the next bookmark's heading."""
    lines: list[str] = []
    for index in range(first, last + 1):
        lines.extend(_page_lines(reader.pages[index].extract_text(extraction_mode="layout")))
    start = _find_heading(lines, title)
    lines = lines[start + 1 if start is not None else 0 :]
    if next_title:
        end = _find_heading(lines, next_title)
        if end is not None:
            lines = lines[:end]
        elif last > first:
            # The next heading wasn't recognised; drop its page rather than borrow from it.
            lines = lines[: len(lines) - len(_page_lines(reader.pages[last].extract_text(extraction_mode="layout")))]
    return _paragraphs(lines)


def _page_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        line = _SPACES.sub(" ", line.strip())
        if _PAGE_FOOTER.search(line):
            continue
        lines.append(_BULLET.sub("- ", line))
    return lines


def _find_heading(lines: list[str], title: str) -> int | None:
    """Index of the line where a bookmark's heading appears ("5.3 HUB" for bookmark "5.3 Hub")."""
    wanted = _normal(title)
    number = title.split(" ", 1)[0]
    for i, line in enumerate(lines):
        normal = _normal(line)
        if normal == wanted or (normal.startswith(wanted) and len(normal) - len(wanted) < 4):
            return i
    for i, line in enumerate(lines):  # heading text differs from the bookmark; match the number
        if re.match(rf"^{re.escape(number)}\s+[A-Z]", line) and len(line) < 80:
            return i
    return None


def _paragraphs(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text + "\n" if text else ""


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
