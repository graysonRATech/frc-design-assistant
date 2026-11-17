"""Convert Astro Starlight MDX pages into plain Markdown suitable for chunking.

JSX components carry most of their meaning in attributes (alt text, link targets, callout
type), so each known component is rewritten into its Markdown equivalent before any
remaining tags are stripped. Fenced code blocks are passed through untouched.
"""

import re
import textwrap

import yaml

from .common import absolutize_links, collapse_blank_lines

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_FENCE = re.compile(r"^\s*(```|~~~)")

_JSX_COMMENT = re.compile(r"\{/\*[\s\S]*?\*/\}")
_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_IMPORT = re.compile(r"""^import\s+(?:[\w*{}\s,]+\s+from\s+)?['"][^'"\n]+['"];?[ \t]*$""", re.MULTILINE)
_EXPORT_START = re.compile(r"^export\s+(?:const|let|var|function|default)\b(?:\s+(\w+))?")
_JS_OBJECT = re.compile(r"\{([^{}]*)\}")
_JS_STRING_FIELD = re.compile(r"""(\w+)\s*:\s*(["'`])((?:\\.|(?!\2).)*)\2""", re.DOTALL)
_CARD_GRID = re.compile(r"<\w+\b[^>]*=\{\s*(\w+)\s*\}[^>]*/>")
_ATTR = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["'`]?([^}"'`]*)["'`]?\s*\})""")

_DIRECTIVE = re.compile(r"^:::(\w+)(?:\[([^\]]*)\])?[^\n]*\n([\s\S]*?)^:::[ \t]*$", re.MULTILINE)
_ASIDE = re.compile(r"<Aside\b([^>]*)>([\s\S]*?)</Aside>")
_FIGURE_SELF_CLOSING = re.compile(r"<ContentFigure\b([^>]*?)/>")
_FIGURE = re.compile(r"<ContentFigure\b([^>]*)>([\s\S]*?)</ContentFigure>")
_LINK_BUTTON = re.compile(r"<LinkButton\b([^>]*)>([\s\S]*?)</LinkButton>")
_CARD = re.compile(r"<(?:CustomCard|ContentCard|HomeCard|LinkCard|Card)\b([^>]*?)/?>")
_TAB_ITEM = re.compile(r"<TabItem\b([^>]*)>")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ANY_TAG = re.compile(r"</?[A-Za-z][\w.:-]*(?:\s[^<>]*?)?/?>")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_PLACEHOLDER_ALT = re.compile(r"(alt text|image|img|picture|photo|(slide|step) ?\d*)", re.IGNORECASE)

_CALLOUT_LABELS = {"note": "Note", "tip": "Tip", "caution": "Caution", "danger": "Danger", "warning": "Warning"}


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body). Malformed frontmatter is treated as empty."""
    text = text.lstrip("﻿")
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def mdx_to_markdown(body: str, page_url: str) -> str:
    parts = []
    for is_code, segment in _split_fences(body):
        converted = textwrap.dedent(segment) if is_code else _convert_prose(segment, page_url)
        if converted.strip():
            parts.append(converted.strip("\n"))
    return collapse_blank_lines("\n\n".join(parts))


def _split_fences(text: str) -> list[tuple[bool, str]]:
    segments: list[tuple[bool, str]] = []
    buffer: list[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if match and not fence:
            segments.append((False, "".join(buffer)))
            buffer, fence = [line], match.group(1)
        elif match and match.group(1) == fence:
            buffer.append(line)
            segments.append((True, "".join(buffer)))
            buffer, fence = [], ""
        else:
            buffer.append(line)
    segments.append((bool(fence), "".join(buffer)))
    return segments


def _convert_prose(text: str, page_url: str) -> str:
    text = _JSX_COMMENT.sub("", text)
    text = _HTML_COMMENT.sub("", text)
    text = _IMPORT.sub("", text)
    text, card_lists = _extract_exports(text)
    # <MechanismCardGrid cards={exampleCards} /> -> the cards as a Markdown list, in place.
    text = _CARD_GRID.sub(lambda m: f"\n{card_lists[m.group(1)]}\n" if m.group(1) in card_lists else "", text)

    text = _DIRECTIVE.sub(_directive, text)
    text = _ASIDE.sub(lambda m: _aside(_attrs(m.group(1)), m.group(2)), text)
    text = _FIGURE_SELF_CLOSING.sub(lambda m: _figure_label(_attrs(m.group(1)).get("alt", "")), text)
    text = _FIGURE.sub(lambda m: _figure(_attrs(m.group(1)).get("alt", ""), m.group(2)), text)
    text = _LINK_BUTTON.sub(lambda m: _link_button(_attrs(m.group(1)), m.group(2)), text)
    text = _CARD.sub(lambda m: _card(_attrs(m.group(1))), text)
    text = _TAB_ITEM.sub(lambda m: f"\n**{_attrs(m.group(1)).get('label', '')}**\n", text)
    text = _MD_IMAGE.sub(lambda m: _figure_label(m.group(1)), text)
    text = _BR.sub("\n", text)
    text = _ANY_TAG.sub("", text)

    text = absolutize_links(text, page_url)
    return _tidy_indentation(text)


def _extract_exports(text: str) -> tuple[str, dict[str, str]]:
    """Remove `export const cards = [...]` blocks, returning card arrays as Markdown lists by name.

    Mechanism pages keep their CAD links and descriptions in these arrays, so they're worth keeping.
    """
    kept: list[str] = []
    card_lists: dict[str, str] = {}
    block: list[str] = []
    name, depth = None, 0
    for line in text.splitlines(keepends=True):
        if not block:
            start = _EXPORT_START.match(line)
            if not start:
                kept.append(line)
                continue
            name, depth = start.group(1), 0
        block.append(line)
        depth += sum(line.count(c) for c in "[{(") - sum(line.count(c) for c in "]})")
        if depth <= 0 and line.rstrip().endswith((";", "]", "}", ")")):
            cards = _cards_from_js("".join(block))
            if name and cards:
                card_lists[name] = cards
            block = []
    return "".join(kept), card_lists


def _cards_from_js(source: str) -> str:
    items = []
    for obj in _JS_OBJECT.finditer(source):
        fields = {m.group(1): m.group(3).replace("\\'", "'").replace('\\"', '"') for m in _JS_STRING_FIELD.finditer(obj.group(1))}
        title = fields.get("title")
        if not title:
            continue
        item = f"- **[{title}]({fields['href']})**" if fields.get("href") else f"- **{title}**"
        if fields.get("description"):
            item += f": {fields['description']}"
        items.append(item)
    return "\n".join(items)


def _attrs(raw: str) -> dict[str, str]:
    return {m.group(1): next(g for g in m.groups()[1:] if g is not None) for m in _ATTR.finditer(raw)}


def _directive(match: re.Match) -> str:
    """Starlight callouts (:::tip) become blockquotes; layout directives (:::center) just unwrap."""
    kind, title, body = match.group(1), match.group(2), match.group(3)
    if kind.lower() in _CALLOUT_LABELS:
        return _callout(title or _callout_label(kind), body)
    return f"\n{textwrap.dedent(body).strip()}\n"


def _callout_label(kind: str) -> str:
    return _CALLOUT_LABELS.get(kind.lower(), kind.title())


def _callout(label: str, body: str) -> str:
    lines = textwrap.dedent(body).strip().splitlines()
    quoted = "\n".join(f"> {line}".rstrip() for line in lines)
    label = label.strip()
    suffix = "" if label.endswith((":", "?", "!", ".")) else ":"
    return f"\n> **{label}{suffix}**\n{quoted}\n"


def _aside(attrs: dict[str, str], body: str) -> str:
    return _callout(attrs.get("title") or _callout_label(attrs.get("type", "note")), body)


def _figure_label(alt: str) -> str:
    """Inline label for an image; inline so images inside table cells don't break the row."""
    alt = alt.strip()
    return f"*[Figure: {alt}]*" if alt and not _PLACEHOLDER_ALT.fullmatch(alt) else ""


def _figure(alt: str, caption: str) -> str:
    parts = [p for p in (_figure_label(alt), textwrap.dedent(caption).strip()) if p]
    return f"\n{'\n\n'.join(parts)}\n" if parts else ""


def _link_button(attrs: dict[str, str], body: str) -> str:
    href = attrs.get("href", "")
    label = " ".join(body.split()) or href
    return f"[{label}]({href})" if href else label


def _card(attrs: dict[str, str]) -> str:
    title, href, description = attrs.get("title", ""), attrs.get("href", ""), attrs.get("description", "")
    if not title:
        return ""
    heading = f"**[{title}]({href})**" if href else f"**{title}**"
    return f"\n{heading}\n{description}\n" if description else f"\n{heading}\n"


def _tidy_indentation(text: str) -> str:
    """Component bodies are indented in the source; keep indentation only where Markdown needs it."""
    lines = [line if _LIST_ITEM.match(line) else line.lstrip() for line in text.splitlines()]
    return "\n".join(lines)
