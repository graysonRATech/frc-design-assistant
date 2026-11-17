"""Heading-aware chunking.

Pages are split at headings, small neighbouring sections are packed together up to a target
size, and oversized sections are split at paragraph boundaries. Every chunk is rendered with
the page title, a breadcrumb and the source URL so it stands on its own for both the
embedding model and the answering model.
"""

import hashlib
import re
import textwrap
from dataclasses import dataclass

from .normalize.common import humanize
from .sources.base import Document

TARGET_CHARS = 2400  # ~600 tokens
MAX_CHARS = 3600  # ~900 tokens
MIN_BODY_CHARS = 60

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]  # enclosing heading titles, outermost first
    anchor: str
    text: str


@dataclass(frozen=True)
class Chunk:
    document: Document
    index: int
    breadcrumb: tuple[str, ...]
    anchor: str
    body: str

    @property
    def url(self) -> str:
        return f"{self.document.url}#{self.anchor}" if self.anchor else self.document.url

    def render(self) -> str:
        crumbs = ([humanize(self.document.section)] if self.document.section else []) + list(self.breadcrumb)
        header = [f"# {self.document.title}"]
        if crumbs:
            header.append("Section: " + " > ".join(crumbs))
        header.append(f"Source: {self.url}")
        return "\n".join(header) + "\n\n" + self.body.strip() + "\n"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.render().encode()).hexdigest()[:16]

    @property
    def est_tokens(self) -> int:
        return estimate_tokens(self.render())


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def chunk_document(
    doc: Document,
    target_chars: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
    min_body_chars: int = MIN_BODY_CHARS,
) -> list[Chunk]:
    pieces: list[Section] = []
    for section in _attach_bare_headings(split_sections(doc.markdown)):
        if len(section.text) <= max_chars:
            pieces.append(section)
        else:
            pieces.extend(
                Section(section.path, section.anchor, part)
                for part in _split_text(section.text, target_chars, max_chars)
            )

    groups: list[list[Section]] = []
    for piece in pieces:
        if groups and sum(len(p.text) + 2 for p in groups[-1]) + len(piece.text) <= target_chars:
            groups[-1].append(piece)
        else:
            groups.append([piece])

    chunks: list[Chunk] = []
    for group in groups:
        body = "\n\n".join(p.text for p in group)
        if len(_without_headings(body)) < min_body_chars:
            continue
        chunks.append(
            Chunk(
                document=doc,
                index=len(chunks),
                breadcrumb=_common_prefix([p.path for p in group]),
                anchor=group[0].anchor,
                body=body,
            )
        )
    return chunks


def split_sections(markdown: str) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    anchor = ""
    in_fence = False

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(Section(tuple(title for _, title in stack), anchor, text))

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading:
            flush()
            buffer = []
            level, title = len(heading.group(1)), _plain(heading.group(2))
            stack = [(lvl, t) for lvl, t in stack if lvl < level] + [(level, title)]
            anchor = heading_anchor(title)
        buffer.append(line)
    flush()
    return sections


def _attach_bare_headings(sections: list[Section]) -> list[Section]:
    """Fold a heading with no text of its own ("## Bolt Sizes" directly followed by
    "### Imperial") into the next section, so a chunk never ends on a dangling heading."""
    merged: list[Section] = []
    pending: Section | None = None
    for section in sections:
        if pending:
            section = Section(
                _common_prefix([pending.path, section.path]), pending.anchor, f"{pending.text}\n\n{section.text}"
            )
            pending = None
        if not _without_headings(section.text):
            pending = section
        else:
            merged.append(section)
    if pending:
        merged.append(pending)
    return merged


def heading_anchor(title: str) -> str:
    """Approximates github-slugger, which Starlight uses for heading ids."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", title.lower()).strip())


def _plain(text: str) -> str:
    return _MD_LINK.sub(r"\1", text).replace("`", "").replace("*", "").strip()


def _without_headings(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _HEADING.match(line)).strip()


def _common_prefix(paths: list[tuple[str, ...]]) -> tuple[str, ...]:
    prefix = paths[0]
    for path in paths[1:]:
        n = 0
        while n < min(len(prefix), len(path)) and prefix[n] == path[n]:
            n += 1
        prefix = prefix[:n]
    return prefix


def _split_text(text: str, target_chars: int, max_chars: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for block in _blocks(text):
        for piece in [block] if len(block) <= max_chars else _hard_split(block, max_chars):
            if current and len(current) + 2 + len(piece) > target_chars:
                parts.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def _blocks(text: str) -> list[str]:
    """Paragraph-level blocks; fenced code and tables stay intact."""
    blocks: list[str] = []
    buffer: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if buffer:
                blocks.append("\n".join(buffer))
                buffer = []
            continue
        buffer.append(line)
    if buffer:
        blocks.append("\n".join(buffer))
    return blocks


def _hard_split(block: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for line in block.splitlines():
        for segment in [line] if len(line) <= max_chars else textwrap.wrap(line, max_chars):
            if current and len(current) + 1 + len(segment) > max_chars:
                pieces.append(current)
                current = segment
            else:
                current = f"{current}\n{segment}" if current else segment
    if current:
        pieces.append(current)
    return pieces
