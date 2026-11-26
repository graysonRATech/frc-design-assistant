import json
from pathlib import Path

import pytest

from frcrag.chunking import chunk_document
from frcrag.config import ConfigError, SourceConfig, load_sources
from frcrag.normalize.html import html_to_markdown
from frcrag.sources.base import FetchResult
from frcrag.sources.github_repo import collect_documents, page_slug, page_url
from frcrag.writer import write_source

SOURCE = SourceConfig(
    id="frcdesign",
    type="github_repo",
    name="FRCDesign.org",
    attribution="FRCDesign.org contributors",
    license_status="attributed",
    refresh="weekly",
    options={"repo": "o/r", "base_url": "https://www.frcdesign.org/", "exclude": ["contribution/*"]},
)


@pytest.mark.parametrize(
    ("rel", "slug", "url"),
    [
        ("index.mdx", "", "https://www.frcdesign.org/"),
        ("learning-course/index.mdx", "learning-course", "https://www.frcdesign.org/learning-course/"),
        (
            "mechanism-examples/pivots/6328_2023_pivot.mdx",
            "mechanism-examples/pivots/6328_2023_pivot",
            "https://www.frcdesign.org/mechanism-examples/pivots/6328_2023_pivot/",
        ),
    ],
)
def test_page_slug_and_url_follow_starlight_routing(rel, slug, url):
    assert page_slug(rel) == slug
    assert page_url("https://www.frcdesign.org", slug) == url


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_collect_documents_applies_filters_and_frontmatter(tmp_path):
    write_tree(
        tmp_path,
        {
            "design-handbook/fasteners.mdx": "---\ntitle: Fasteners\n---\n## Bolts\n\nUse #10-32.",
            "design-handbook/draft.mdx": "---\ntitle: WIP\ndraft: true\n---\nSoon.",
            "contribution/styleguide.mdx": "---\ntitle: Style\n---\nRules.",
            "design-handbook/img/a.webp": "not a doc",
        },
    )
    docs = list(collect_documents(tmp_path, SOURCE))
    assert [d.doc_id for d in docs] == ["design-handbook/fasteners"]
    assert docs[0].title == "Fasteners"
    assert docs[0].section == "design-handbook"
    assert docs[0].url == "https://www.frcdesign.org/design-handbook/fasteners/"


def test_writer_emits_bedrock_layout_and_manifest(tmp_path):
    write_tree(tmp_path / "src", {"design-handbook/fasteners.mdx": "---\ntitle: Fasteners\n---\n## Bolts\n\n" + "Use #10-32. " * 20})
    docs = list(collect_documents(tmp_path / "src", SOURCE))
    chunks = [c for d in docs for c in chunk_document(d)]
    out = tmp_path / "build"
    (out / "frcdesign").mkdir(parents=True)
    (out / "frcdesign" / "stale--000.md").write_text("old", encoding="utf-8")

    manifest_path = write_source(SOURCE, FetchResult(docs, "o/r@abc"), chunks, out)

    files = sorted(p.name for p in (out / "frcdesign").iterdir())
    assert files == ["design-handbook__fasteners--000.md", "design-handbook__fasteners--000.md.metadata.json"]
    meta = json.loads((out / "frcdesign" / files[1]).read_text(encoding="utf-8"))["metadataAttributes"]
    assert meta["url"] == "https://www.frcdesign.org/design-handbook/fasteners/#bolts"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["revision"] == "o/r@abc" and len(manifest["chunks"]) == 1
    assert manifest_path.parent.name == "_manifests"


def test_load_sources_validates(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources:\n  - id: frcdesign\n    type: github_repo\n    repo: o/r\n    base_url: https://x/\n", encoding="utf-8")
    [source] = load_sources(path)
    assert source.options == {"repo": "o/r", "base_url": "https://x/"}

    path.write_text("sources:\n  - id: Bad_ID\n    type: sitemap\n    url: https://x/\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_sources(path)
    path.write_text("sources:\n  - id: wcp\n    type: sitemap\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="require url"):
        load_sources(path)


def test_the_repo_sources_file_is_valid():
    assert [s.id for s in load_sources(Path(__file__).parents[1] / "sources.yaml")] == ["frcdesign", "game-manual", "past-games"]


def test_html_to_markdown_strips_site_chrome():
    html = """<html><head><title>Gears | Site</title></head><body>
      <header>Site nav</header><nav>Sidebar</nav>
      <main><h1 id="_top">Gears</h1>
        <div data-pagefind-body>
          <h2 id="pitch">Pitch<a class="sl-anchor-link" href="#pitch"><span class="sr-only">Section titled Pitch</span></a></h2>
          <p>FRC gears are 20 DP. See <a href="../belts/">belts</a>.</p>
          <aside><p>Tip: use hex bore.</p></aside>
        </div>
      </main><footer>Sponsors</footer></body></html>"""
    title, md = html_to_markdown(html, "https://example.org/docs/gears/")
    assert title == "Gears"
    assert "## Pitch" in md and "Section titled" not in md
    assert "[belts](https://example.org/docs/belts/)" in md
    assert "Tip: use hex bore." in md
    assert "Sidebar" not in md and "Sponsors" not in md and "Site nav" not in md


def test_writer_omits_empty_metadata_values(tmp_path):
    # A top-level page has no site section; Bedrock rejects files with empty-string attributes.
    write_tree(tmp_path / "src", {"index.mdx": "---\ntitle: Welcome\n---\n" + "Start here. " * 20})
    docs = list(collect_documents(tmp_path / "src", SOURCE))
    write_source(SOURCE, FetchResult(docs, "o/r@abc"), [c for d in docs for c in chunk_document(d)], tmp_path / "build")
    [meta_file] = (tmp_path / "build" / "frcdesign").glob("*.metadata.json")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))["metadataAttributes"]
    assert "site_section" not in meta and all(meta.values())
