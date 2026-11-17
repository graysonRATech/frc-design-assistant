"""Helpers shared by the MDX and HTML normalizers."""

import re
from urllib.parse import urljoin

# [text](target "optional title"), but not images (![alt](src)).
_LINK = re.compile(r'(?<!!)\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)')
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def absolutize_links(markdown: str, base_url: str) -> str:
    """Rewrite relative links against the page URL so citations work outside the site."""

    def replace(match: re.Match) -> str:
        text, target = match.group(1), match.group(2)
        if _HAS_SCHEME.match(target):
            return match.group(0)
        return f"[{text}]({urljoin(base_url, target)})"

    return _LINK.sub(replace, markdown)


def collapse_blank_lines(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def humanize(slug: str) -> str:
    """'design-handbook' -> 'Design Handbook'."""
    return re.sub(r"[-_]+", " ", slug).strip().title()
