"""Ingest the FRC game manual from FIRST's HTML edition (a Microsoft Word "filtered HTML" export).

Every rule (R103, G204, ...) becomes its own document, cited with a link straight to the rule:
FIRST's HTML puts an anchor named after each rule number. Prose between rules (field
descriptions, scoring, tournament structure) becomes one document per numbered subsection.

FIRST revises the manual through Team Updates during the season and republishes the HTML at the
same address, so a daily refresh keeps answers on the current wording. With `next_season: true`
the fetcher looks for next season's manual first, so on kickoff day the new game replaces the old
one without anyone editing sources.yaml.
"""

import codecs
import hashlib
import logging
import re
import urllib.error
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdownify import markdownify

from .. import http
from ..config import SourceConfig
from .base import Document, FetchResult

log = logging.getLogger(__name__)

_RULE_ID = re.compile(r"^[A-Z]\d{3}$")
_SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\s+")
_CHAPTER_LETTER = re.compile(r"\s*\([A-Z]\)\s*$")
_CHARSET = re.compile(rb"charset=[\"']?([\w-]+)", re.IGNORECASE)
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def fetch(source: SourceConfig, cache_dir: Path) -> FetchResult:
    opts = source.options
    year = int(opts["year"])
    years = [year + 1, year] if opts.get("next_season") else [year]
    for candidate in years:
        url = opts["url"].format(year=candidate)
        try:
            raw = http.get(url, timeout=120)
        except urllib.error.HTTPError as error:
            if error.code in (403, 404) and candidate != years[-1]:
                log.info("%s: no %d manual yet (%s)", source.id, candidate, error.code)
                continue
            raise
        documents = parse_manual(decode(raw), url, source.id, candidate)
        log.info("%s: %d game manual, %d rules", source.id, candidate, sum(d.doc_id.startswith("rules/") for d in documents))
        return FetchResult(documents=documents, revision=f"{url} sha256:{hashlib.sha256(raw).hexdigest()[:16]}")
    raise AssertionError("unreachable: the last candidate year raises instead of continuing")


def decode(raw: bytes) -> str:
    """Word declares its encoding in a meta tag; FIRST's export uses Mac Roman ("macintosh")."""
    match = _CHARSET.search(raw[:4096])
    if match:
        try:
            return raw.decode(codecs.lookup(match.group(1).decode("ascii")).name)
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_manual(html: str, url: str, source_id: str, year: int) -> list[Document]:
    soup = BeautifulSoup(html, "html.parser")
    manual = f"{year} Game Manual"
    documents: list[Document] = []
    seen: set[str] = set()

    chapter = ""  # e.g. "Robot Construction Rules", for breadcrumbs
    heading, anchor = "", ""  # the current numbered section, e.g. "8.1 General ROBOT Design"
    prose: list[str] = []
    rule: tuple[str, str, list[str]] | None = None  # (number, headline, blocks)

    def add(doc_id: str, title: str, link: str, blocks: list[str]) -> None:
        markdown = "\n\n".join(b for b in blocks if b).strip()
        if not markdown:
            return
        base, n = doc_id, 2
        while doc_id in seen:
            doc_id, n = f"{base}-{n}", n + 1
        seen.add(doc_id)
        documents.append(
            Document(
                source_id=source_id,
                doc_id=doc_id,
                url=link,
                title=title,
                section=_slug(chapter),
                markdown=markdown + "\n",
                description=heading,
                min_body_chars=0 if doc_id.startswith("rules/") else None,  # "E503 Keep aisles clear." is a whole rule
            )
        )

    def end_rule() -> None:
        nonlocal rule
        if rule:
            number, headline, blocks = rule
            title = f"{manual} {number}: {headline}" if headline else f"{manual} {number}"
            add(f"rules/{number.lower()}", title, f"{url}#{number}", blocks)
        rule = None

    def end_section() -> None:
        end_rule()
        if heading:
            number = _SECTION_NUMBER.match(heading)
            doc_id = f"sections/{number.group(1) if number else _slug(heading)}"
            add(doc_id, f"{manual} {heading}", f"{url}#{anchor}" if anchor else url, prose)
        prose.clear()

    started = False
    for block in _blocks(soup.body or soup):
        if block.name in _HEADINGS:
            text = _text(block)
            if block.name == "h1":
                started = True
            if not started or not text:
                continue
            if block.name in ("h1", "h2"):
                end_section()
                heading, anchor = text, _anchor(block)
                if block.name == "h1":
                    chapter = _CHAPTER_LETTER.sub("", _SECTION_NUMBER.sub("", text))
                continue
            end_rule()
            prose.append(f"**{text}**")  # a heading in the body would give the chunk a bad link
            continue
        if not started:
            continue  # cover page and table of contents

        classes = " ".join(block.get("class", []))
        number = _rule_number(block) if block.name == "p" else ""
        if number:
            end_rule()
            headline, body = _rule_parts(block, number)
            rule = (number, headline, [f"**{number}** *{headline}* {body}".strip() if headline else f"**{number}** {body}"])
            continue
        markdown = _block_markdown(block, classes)
        if rule:
            rule[2].append(markdown)
        else:
            prose.append(markdown)
    end_section()
    return documents


def _blocks(root: Tag):
    """Content blocks in document order: headings, paragraphs, tables and "blue box" notes."""
    for child in root.children:
        if not isinstance(child, Tag):
            continue
        if child.name in _HEADINGS or child.name in ("p", "table", "ul", "ol"):
            if child.name == "p" and any(c.startswith("MsoToc") for c in child.get("class", [])):
                continue
            yield child
        elif child.name == "div" and child.find("p", class_=re.compile(r"^BlueBox"), recursive=False):
            yield child
        else:
            yield from _blocks(child)


def _block_markdown(block: Tag, classes: str) -> str:
    if block.name == "div":  # a "blue box": FIRST's explanatory note under a rule
        notes = [_text(p) for p in block.find_all("p")]
        return "\n>\n".join(f"> {note}" for note in notes if note)
    if block.name == "table":
        return _table(block)
    if block.name in ("ul", "ol"):
        return "\n".join(f"- {_text(li)}" for li in block.find_all("li"))
    text = _text(block)
    if classes.startswith("Violation") and text.lower().startswith("violation:"):
        return f"**Violation:**{text[len('violation:'):]}"
    if classes.startswith("MsoCaption") and text:
        return f"*{text}*"
    return text


def _rule_number(paragraph: Tag) -> str:
    """The rule a paragraph starts, or "". Word styles rules inconsistently (RuleNumber-Robot,
    RuleNumberT, TRules-Evergreen, ...) and reuses those styles for continuation paragraphs, so
    a rule is recognised by its anchor (<a name="R103">) plus text that opens with that number."""
    for link in paragraph.find_all("a", attrs={"name": True}):
        if _RULE_ID.match(link["name"]) and _text(paragraph).startswith(link["name"]):
            return link["name"]
    return ""


def _rule_parts(paragraph: Tag, number: str) -> tuple[str, str]:
    """(headline, rest of the text) for a rule's first paragraph."""
    text = _text(paragraph)[len(number) :].strip()
    headline = re.sub(r"\s+", " ", " ".join(_text(s) for s in paragraph.find_all("span", class_=re.compile(r"^Headline")))).strip()
    if headline and text.startswith(headline):
        text = text[len(headline) :].strip()
    return headline.lstrip("*").strip(), text


def _table(table: Tag) -> str:
    rows = [[_text(cell) for cell in row.find_all(["td", "th"])] for row in table.find_all("tr")]
    rows = [row for row in rows if any(row)]
    if rows and all(len(row) == 2 for row in rows):  # term/definition tables, like the glossary
        return "\n\n".join(f"**{term}**: {definition}" if term else definition for term, definition in rows)
    return markdownify(str(table), heading_style="ATX", strip=["img", "a"]).strip()


def _text(tag: Tag) -> str:
    """Visible text on one line. Word hard-wraps its HTML at ~80 columns, so line breaks in the
    source mean nothing; a <br> inside a paragraph reads fine as a space."""
    parts = []
    for node in tag.descendants:
        if isinstance(node, Comment):
            continue
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif node.name == "br":
            parts.append(" ")
    text = "".join(parts)
    return re.sub(r"\s+", " ", text).strip()


def _anchor(heading: Tag) -> str:
    """The bookmark Word puts on a heading (_Toc... or _Ref...), for a link to that section."""
    link = heading.find("a", attrs={"name": True})
    return link["name"] if link else ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
