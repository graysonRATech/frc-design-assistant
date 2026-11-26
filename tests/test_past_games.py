from types import SimpleNamespace

from frcrag.chunking import chunk_document
from frcrag.sources.past_games import game_documents

URL = "https://firstfrc.blob.core.windows.net/frc2022/Manual/2022FRCGameManual.pdf"
GAME = {"year": 2022, "name": "RAPID REACT", "chapters": [4, 5], "url": URL}


class FakeReader:
    """The parts of pypdf's PdfReader the source uses: bookmarks, pages and their text."""

    def __init__(self, pages: list[str], outline: list):
        self.pages = [SimpleNamespace(extract_text=lambda extraction_mode=None, t=t: t) for t in pages]
        self.outline = outline

    def get_destination_page_number(self, item):
        return item.page


def mark(title, page):
    return SimpleNamespace(title=title, page=page)


PAGES = [
    "4      GAME OVERVIEW\n\nIn RAPID REACT, alliances score CARGO\ninto the HUB by:\n\n    taxiing and\n    scoring.\n\n4 Game Overview          V0          17 of 136",
    "5      ARENA\nThe ARENA includes the FIELD.\n5.1 Field\nThe FIELD is carpeted.\n5.2 Hub\nThe HUB is 8 ft. 11 in. wide.",
    "The HUB has an agitator.\n6      MATCH PLAY\nMATCHES last 2:30.",
    "7      GAME RULES: ROBOTS\nG101 Robots must not ...",
]
OUTLINE = [
    mark("4 Game Overview", 0),
    mark("5 ARENA", 1),
    [mark("5.1 Field", 1), mark("5.2 Hub", 1), [mark("5.2.1 Agitator", 2)]],
    mark("6 MATCH Play", 2),
    mark("7 Game Rules: ROBOTS", 3),
]


def documents():
    return {d.doc_id: d for d in game_documents(FakeReader(PAGES, OUTLINE), GAME, "past-games")}


def test_only_the_chosen_chapters_become_documents():
    assert sorted(documents()) == ["2022/4-game-overview", "2022/5-1-field", "2022/5-2-hub", "2022/5-arena"]


def test_sections_are_titled_as_past_games_and_linked_to_their_page():
    hub = documents()["2022/5-2-hub"]
    assert hub.title == "Past game: 2022 RAPID REACT, 5.2 Hub"
    assert hub.url == f"{URL}#page=2"
    assert hub.section == "2022-rapid-react"


def test_section_text_runs_from_its_heading_to_the_next_bookmark():
    docs = documents()
    assert docs["2022/5-arena"].markdown == "The ARENA includes the FIELD.\n"
    assert docs["2022/5-1-field"].markdown == "The FIELD is carpeted.\n"
    # 5.2 continues onto the next page and stops at chapter 6; deeper bookmarks stay inside it.
    assert docs["2022/5-2-hub"].markdown == "The HUB is 8 ft. 11 in. wide.\nThe HUB has an agitator.\n"


def test_bullets_and_page_footers_are_cleaned():
    text = documents()["2022/4-game-overview"].markdown
    assert "- taxiing and\n- scoring." in text
    assert "17 of 136" not in text
    assert "GAME OVERVIEW" not in text  # the heading is the title, not body text


def test_chunks_render_as_past_games():
    chunk = chunk_document(documents()["2022/4-game-overview"])[0]
    assert chunk.render().startswith("# Past game: 2022 RAPID REACT, 4 Game Overview\nSection: 2022 Rapid React\n")
