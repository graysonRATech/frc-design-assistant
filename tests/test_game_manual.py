import urllib.error

import pytest

from frcrag.chunking import chunk_document
from frcrag.config import SourceConfig
from frcrag.sources import game_manual
from frcrag.sources.game_manual import decode, parse_manual

URL = "https://firstfrc.blob.core.windows.net/frc2026/Manual/HTML/2026GameManual.htm"

# The shapes of FIRST's Word export, cut down: a cover and table of contents before the first
# chapter, anchors Word wraps onto a new line, rule styles that differ by chapter, continuation
# paragraphs that reuse the rule style, "blue box" notes, and a two-column glossary table.
MANUAL = """<html><head><meta http-equiv=Content-Type content="text/html; charset=macintosh"></head>
<body><div class=WordSection1>
<p class=MsoTitle>2026 FIRST Robotics Competition</p>
<p class=MsoToc1><a href="#_Toc1">8 ROBOT Construction Rules</a></p>
</div><div class=WordSection2>
<h1><a name="_Toc1"></a>8 ROBOT Construction Rules (R)</h1>
<p class=MsoNormal>ROBOT rules apply to every ROBOT.</p>
<h2><a name="_Toc2"></a>8.1 General ROBOT Design</h2>
<p class="RuleNumber-Robot"><a name="R103"></a><b>R103<span>\xa0\xa0\xa0\r\n</span></b><span
class="Headline-Evergreen">*ROBOT weight limit.</span> The ROBOT weight must not
exceed 115.0lb (52.16kg). The following items are excluded:</p>
<p class="Rule-LetteredListCxSpFirst">A.<span>\xa0\xa0</span>ROBOT BUMPERS,</p>
<p class="RuleNumber-Robot">B.<span>\xa0\xa0</span>the ROBOT battery.</p>
<div style="border:solid #0083AE 1.5pt">
<p class=BlueBox>Weigh the ROBOT with every MECHANISM it might use.</p>
<p class=BlueBox>\xa0</p>
</div>
<p class=Violation>Violation: The ROBOT will not pass inspection.</p>
<p class="RuleNumber-Robot"><a
name=R104></a><b>R104 </b><span class="Headline-Evergreen">*Don’t exceed the frame.</span> Stay
inside the ROBOT PERIMETER.</p>
<h3>Bumper materials</h3>
<p class=MsoNormal>Pool noodles are common.</p>
<h1><a name="_Toc3"></a>10 Tournaments (T)</h1>
<h2><a name="_Toc4"></a>10.6 Playoff MATCHES</h2>
<p class="TRules-Evergreen"><a name="T603"></a><b>T603 </b><span class="Headline-Evergreen">*</span>
<span class="Headline-Evergreen">Only STUDENTS may use the mic.</span> Only a STUDENT may accept.</p>
<h1><a name="_Toc5"></a>14 Event Rules (E)</h1>
<p class="RuleNumber-Event"><a name="E503"></a><b>E503 </b><span class="Headline-Evergreen">*Keep aisles clear.</span> Aisles must be kept clear.</p>
<h1><a name="_Toc6"></a>15 Glossary</h1>
<table><tr><td><p>Term</p></td><td><p>Definition</p></td></tr>
<tr><td><p>COTS</p></td><td><p>a standard part commonly available from a VENDOR</p></td></tr></table>
</div></body></html>""".encode("mac_roman")


@pytest.fixture
def documents():
    return {d.doc_id: d for d in parse_manual(decode(MANUAL), URL, "game-manual", 2026)}


def test_each_rule_is_a_document_linked_to_its_anchor(documents):
    assert sorted(k for k in documents if k.startswith("rules/")) == ["rules/e503", "rules/r103", "rules/r104", "rules/t603"]
    r103 = documents["rules/r103"]
    assert r103.title == "2026 Game Manual R103: ROBOT weight limit."
    assert r103.url == f"{URL}#R103"
    assert r103.section == "robot-construction-rules"
    assert documents["rules/t603"].title == "2026 Game Manual T603: Only STUDENTS may use the mic."


def test_rule_keeps_its_lists_notes_and_violation(documents):
    text = documents["rules/r103"].markdown
    assert text.startswith("**R103** *ROBOT weight limit.* The ROBOT weight must not exceed 115.0lb (52.16kg).")
    assert "A. ROBOT BUMPERS," in text
    assert "B. the ROBOT battery." in text  # styled like a rule, but no rule anchor: still part of R103
    assert "> Weigh the ROBOT with every MECHANISM it might use." in text
    assert "\n>\n>" not in text  # the empty note paragraph is dropped
    assert "**Violation:** The ROBOT will not pass inspection." in text
    assert "R104" not in text


def test_mac_roman_and_wrapped_anchors(documents):
    r104 = documents["rules/r104"]
    assert r104.title == "2026 Game Manual R104: Don’t exceed the frame."
    assert r104.markdown.strip() == "**R104** *Don’t exceed the frame.* Stay inside the ROBOT PERIMETER."


def test_prose_is_split_by_numbered_section_without_body_headings(documents):
    chapter = documents["sections/8"]
    assert chapter.title == "2026 Game Manual 8 ROBOT Construction Rules (R)"
    assert chapter.url == f"{URL}#_Toc1"
    assert chapter.markdown.strip() == "ROBOT rules apply to every ROBOT."
    # The h3 after R104 ends the rule; its text goes to the section, bold rather than a heading,
    # so the chunker doesn't append a heading slug to a URL that already has a #fragment.
    assert documents["sections/8.1"].markdown.strip() == "**Bumper materials**\n\nPool noodles are common."
    assert documents["sections/8.1"].url == f"{URL}#_Toc2"
    assert not any("2026 FIRST Robotics Competition" in d.markdown for d in documents.values())  # cover page


def test_glossary_rows_become_definitions(documents):
    assert "**COTS**: a standard part commonly available from a VENDOR" in documents["sections/15"].markdown


def test_short_rules_survive_chunking(documents):
    chunks = chunk_document(documents["rules/e503"])
    assert len(chunks) == 1
    assert chunks[0].url == f"{URL}#E503"
    assert "Aisles must be kept clear." in chunks[0].render()


def source(**options):
    return SourceConfig(
        id="game-manual",
        type="game_manual",
        name="FRC Game Manual",
        attribution="FIRST",
        license_status="attributed",
        refresh="daily",
        options={"url": "https://x/frc{year}/{year}GameManual.htm", "year": 2026, **options},
    )


def not_found(url):
    return urllib.error.HTTPError(url, 404, "Not Found", None, None)


def test_next_season_falls_back_until_kickoff(monkeypatch, tmp_path):
    requested = []

    def get(url, **_):
        requested.append(url)
        if "2027" in url:
            raise not_found(url)
        return MANUAL

    monkeypatch.setattr(game_manual.http, "get", get)
    result = game_manual.fetch(source(next_season=True), tmp_path)
    assert requested == ["https://x/frc2027/2027GameManual.htm", "https://x/frc2026/2026GameManual.htm"]
    assert result.revision.startswith("https://x/frc2026/2026GameManual.htm sha256:")
    assert result.documents[0].title.startswith("2026 Game Manual")


def test_next_season_switches_on_kickoff(monkeypatch, tmp_path):
    monkeypatch.setattr(game_manual.http, "get", lambda url, **_: MANUAL)
    result = game_manual.fetch(source(next_season=True), tmp_path)
    assert result.revision.startswith("https://x/frc2027/")
    assert all(d.title.startswith("2027 Game Manual") for d in result.documents)


def test_missing_current_manual_is_an_error(monkeypatch, tmp_path):
    def get(url, **_):
        raise not_found(url)

    monkeypatch.setattr(game_manual.http, "get", get)
    with pytest.raises(urllib.error.HTTPError):
        game_manual.fetch(source(next_season=True), tmp_path)
