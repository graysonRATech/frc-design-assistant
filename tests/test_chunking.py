from frcrag.chunking import chunk_document, heading_anchor, split_sections
from frcrag.sources.base import Document


def make_doc(markdown: str) -> Document:
    return Document(
        source_id="frcdesign",
        doc_id="design-handbook/structure/fasteners",
        url="https://www.frcdesign.org/design-handbook/structure/fasteners/",
        title="Fasteners",
        section="design-handbook",
        markdown=markdown,
    )


def test_sections_track_heading_breadcrumbs():
    md = "Intro text.\n\n## Bolts\n\nBolt text.\n\n### Imperial\n\nImperial text.\n\n## Nuts\n\nNut text."
    sections = split_sections(md)
    assert [s.path for s in sections] == [(), ("Bolts",), ("Bolts", "Imperial"), ("Nuts",)]
    assert sections[2].anchor == "imperial"


def test_hash_lines_inside_code_fences_are_not_headings():
    sections = split_sections("## Real\n\n```python\n# not a heading\n```\n")
    assert len(sections) == 1 and sections[0].path == ("Real",)


def test_small_sections_are_merged_with_common_breadcrumb():
    md = "## Bolts\n\n" + "a" * 100 + "\n\n### Imperial\n\n" + "b" * 100 + "\n\n### Metric\n\n" + "c" * 100
    chunks = chunk_document(make_doc(md))
    assert len(chunks) == 1
    assert chunks[0].breadcrumb == ("Bolts",)
    assert chunks[0].url.endswith("/fasteners/#bolts")


def test_oversized_sections_are_split_under_max():
    paragraphs = "\n\n".join(f"Paragraph {i} " + "x" * 500 for i in range(20))
    chunks = chunk_document(make_doc("## Long\n\n" + paragraphs), target_chars=2400, max_chars=3600)
    assert len(chunks) > 1
    assert all(len(c.body) <= 3600 for c in chunks)
    assert all(c.breadcrumb == ("Long",) for c in chunks)
    joined = "\n\n".join(c.body for c in chunks)
    assert all(f"Paragraph {i} " in joined for i in range(20))


def test_a_single_huge_line_is_hard_split():
    chunks = chunk_document(make_doc("## Wall\n\n" + "word " * 2000), max_chars=3600)
    assert len(chunks) > 1 and all(len(c.body) <= 3600 for c in chunks)


def test_bare_heading_joins_the_following_section():
    md = "## Bolts\n\n" + "a" * 2300 + "\n\n## Bolt Sizes\n\n### Imperial\n\n" + "b" * 300
    first, second = chunk_document(make_doc(md))
    assert not first.body.rstrip().endswith("## Bolt Sizes")
    assert second.body.startswith("## Bolt Sizes\n\n### Imperial")
    assert second.breadcrumb == ("Bolt Sizes",) and second.anchor == "bolt-sizes"


def test_heading_only_chunks_are_dropped():
    assert chunk_document(make_doc("## Empty\n\n### Also empty")) == []


def test_render_includes_context_header():
    rendered = chunk_document(make_doc("## Bolts\n\nUse #10-32 for almost everything on the robot; use 1/4-20 where you need more strength."))[0].render()
    assert rendered.startswith(
        "# Fasteners\nSection: Design Handbook > Bolts\n"
        "Source: https://www.frcdesign.org/design-handbook/structure/fasteners/#bolts\n\n## Bolts"
    )


def test_heading_anchor_matches_starlight_style():
    assert heading_anchor("Why Put Fasteners in CAD?") == "why-put-fasteners-in-cad"
    assert heading_anchor("#10-32 vs. 1/4\"-20") == "10-32-vs-14-20"
