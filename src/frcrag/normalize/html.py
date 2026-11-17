"""Convert a rendered documentation page into Markdown (for sitemap sources)."""

from bs4 import BeautifulSoup
from markdownify import markdownify

from .common import absolutize_links, collapse_blank_lines

_CHROME_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "button", "iframe", "template", "dialog"]
# Screen-reader-only text and heading anchor icons duplicate the visible heading text.
_CHROME_SELECTORS = ".sr-only, .sl-anchor-link, .headerlink, [aria-hidden='true']"


def html_to_markdown(html: str, url: str) -> tuple[str, str]:
    """Return (title, markdown) for the main content of a page."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True)
    else:
        title = url

    root = soup.select_one("[data-pagefind-body]") or soup.find("main") or soup.find("article") or soup.body or soup
    for tag in root.find_all(_CHROME_TAGS):
        tag.decompose()
    for tag in root.select(_CHROME_SELECTORS):
        tag.decompose()
    for tag in root.find_all("h1"):
        tag.decompose()

    markdown = markdownify(str(root), heading_style="ATX", bullets="-", strip=["img"])
    return title, collapse_blank_lines(absolutize_links(markdown, url))
