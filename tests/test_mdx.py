from frcrag.normalize.mdx import mdx_to_markdown, split_frontmatter

URL = "https://www.frcdesign.org/design-handbook/structure/fasteners/"


def test_frontmatter_with_bom_is_parsed_and_removed():
    meta, body = split_frontmatter("﻿---\ntitle: Fasteners\ndescription: Bolts\n---\n\nHello")
    assert meta == {"title": "Fasteners", "description": "Bolts"}
    assert body.strip() == "Hello"


def test_missing_or_malformed_frontmatter_yields_empty_dict():
    assert split_frontmatter("No frontmatter")[0] == {}
    assert split_frontmatter("---\n: [unclosed\n---\nbody")[0] == {}


def test_imports_and_export_blocks_are_removed():
    text = (
        "import ContentRow from '@components/content/ContentRow.astro';\n"
        "import { Tabs, TabItem } from '@astrojs/starlight/components';\n"
        "export const cards = [\n  { title: 'A', href: '/a/' },\n];\n\n"
        "import the part into your assembly.\n"
    )
    out = mdx_to_markdown(text, URL)
    assert "@components" not in out and "cards" not in out
    assert "import the part into your assembly." in out  # prose starting with "import" survives


def test_exported_card_arrays_render_where_the_grid_was():
    text = (
        "import MechanismCardGrid from '@components/content/MechanismCardGrid.astro';\n"
        "export const exampleCards = [\n"
        "  {\n    title: \"1678's Charged Up Elevator\",\n"
        "    href: 'https://cad.onshape.com/documents/9ba/w/dce',\n    image: elevator1678,\n"
        "    description: 'A cable driven two-stage continuous elevator.',\n  },\n"
        "  { title: 'No link', description: \"It's a card\" },\n"
        "];\n\nElevators with continuous rigging.\n\n## CAD References\n\n"
        "<MechanismCardGrid cards={exampleCards} />\n"
    )
    out = mdx_to_markdown(text, URL)
    assert out.index("Elevators with continuous rigging.") < out.index("## CAD References") < out.index("- **[1678")
    assert "- **[1678's Charged Up Elevator](https://cad.onshape.com/documents/9ba/w/dce)**: A cable driven" in out
    assert "- **No link**: It's a card" in out
    assert "export" not in out and "elevator1678" not in out


def test_aside_becomes_labelled_blockquote():
    out = mdx_to_markdown('<Aside type="tip">\nUse the Replicate tool.\n</Aside>', URL)
    assert out.strip() == "> **Tip:**\n> Use the Replicate tool."


def test_starlight_directive_becomes_blockquote():
    out = mdx_to_markdown(":::caution[Pinch point]\nKeep fingers clear.\n:::", URL)
    assert out.strip() == "> **Pinch point:**\n> Keep fingers clear."


def test_layout_directives_are_unwrapped():
    assert mdx_to_markdown(":::center\n**`PD = teeth / DP`**\n:::", URL).strip() == "**`PD = teeth / DP`**"


def test_figures_keep_alt_text_and_captions():
    text = (
        '<ContentFigure src="./a.webp" alt="Socket Head Cap Screw" />\n\n'
        '<ContentFigure src="./b.webp" alt="1678 Backrollers" width="40%">\n'
        "  Backrollers control backspin.\n</ContentFigure>\n\n"
        '<ContentFigure src="./c.webp" alt="" />\n'
        "![Alt text](./img/step1.webp)\n"
    )
    out = mdx_to_markdown(text, URL)
    assert "*[Figure: Socket Head Cap Screw]*" in out
    assert "*[Figure: 1678 Backrollers]*\n\nBackrollers control backspin." in out
    assert "c.webp" not in out and "Alt text" not in out and "step1" not in out


def test_link_buttons_and_cards_become_links():
    text = (
        '<LinkButton href="https://cad.onshape.com/documents/abc/w/def" center>\n  CAD Document\n</LinkButton>\n\n'
        '<CustomCard title="Origin Cube" subTitle="" href="https://cad.onshape.com/documents/xyz">\n<hr/>\nBody\n</CustomCard>'
    )
    out = mdx_to_markdown(text, URL)
    assert "[CAD Document](https://cad.onshape.com/documents/abc/w/def)" in out
    assert "**[Origin Cube](https://cad.onshape.com/documents/xyz)**" in out
    assert "<hr" not in out and "</CustomCard>" not in out


def test_tabs_keep_labels():
    text = '<Tabs>\n  <TabItem label="Beginner Challenge">\n    * Choose a COTS swerve module\n  </TabItem>\n</Tabs>'
    out = mdx_to_markdown(text, URL)
    assert "**Beginner Challenge**" in out
    assert "* Choose a COTS swerve module" in out
    assert "<" not in out


def test_relative_links_are_absolutized():
    out = mdx_to_markdown("See [gears](../../power-transmission/gears/) and [top](#bolts).", URL)
    assert "[gears](https://www.frcdesign.org/design-handbook/power-transmission/gears/)" in out
    assert f"[top]({URL}#bolts)" in out


def test_code_fences_are_untouched():
    text = "Intro\n\n```mdx\n<Aside type=\"tip\">x</Aside>\nimport A from 'a';\n```\n"
    out = mdx_to_markdown(text, URL)
    assert "```mdx\n<Aside type=\"tip\">x</Aside>\nimport A from 'a';\n```" in out


def test_tables_and_comparisons_survive():
    text = "| Type | Use |\n|---|---|\n| **SHCS** | General <ContentFigure src=\"x\" alt=\"\" /> |\n\nUse a ratio < 3 for this."
    out = mdx_to_markdown(text, URL)
    assert "| **SHCS** | General |" in out.replace("  ", " ")
    assert "ratio < 3" in out


def test_figures_in_table_cells_stay_on_the_row():
    text = '| Type | Image |\n|---|---|\n| SHCS | <ContentFigure src="x.webp" alt="Socket Head Cap Screw" /> |\n'
    assert "| SHCS | *[Figure: Socket Head Cap Screw]* |" in mdx_to_markdown(text, URL)
