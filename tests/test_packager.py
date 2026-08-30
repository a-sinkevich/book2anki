import json
import os
import sqlite3
import tempfile
import zipfile

from book2anki.models import Card, is_cloze
from book2anki.packager import (
    CARD_MODEL,
    CLOZE_MODEL,
    _gap_context,
    _model_tag,
    _split_etymology,
    _read_cards_from_apkg,
    _slugify,
    _slugify_for_filename,
    _stable_id,
    chapter_filename,
    load_existing_chapters,
    package_cards,
    package_practice,
    package_practice_chapter,
    package_single_chapter,
    package_vocab_production,
)


def _note_tags(path: str) -> list[list[str]]:
    with zipfile.ZipFile(path, "r") as zf:
        db_name = next(n for n in zf.namelist() if n.startswith("collection.anki2"))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(zf.read(db_name))
            tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute("SELECT tags FROM notes").fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)
    return [tags.strip().split() for (tags,) in rows]


def _deck_names(path: str) -> list[str]:
    with zipfile.ZipFile(path, "r") as zf:
        db_name = next(n for n in zf.namelist() if n.startswith("collection.anki2"))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(zf.read(db_name))
            tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        row = conn.execute("SELECT decks FROM col").fetchone()
        conn.close()
    finally:
        os.unlink(tmp_path)
    decks = json.loads(row[0])
    return [
        deck["name"]
        for deck in decks.values()
        if deck["name"] != "Default"
    ]


def test_stable_id_deterministic():
    assert _stable_id("hello") == _stable_id("hello")


def test_stable_id_different_inputs():
    assert _stable_id("hello") != _stable_id("world")


def test_slugify_basic():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    assert _slugify("Chapter 1: The Beginning!") == "chapter-1-the-beginning"


def test_model_tag_preserves_exact_model_version():
    assert _model_tag("gpt-5.5") == "model::gpt-5.5"
    assert _model_tag("cli:claude-opus-4-8") == "model::cli::claude-opus-4-8"


def test_slugify_cyrillic():
    result = _slugify("Глава первая")
    assert "глава" in result
    assert "первая" in result


def test_slugify_for_filename_strips_number_prefix():
    assert _slugify_for_filename("1. Trade-Offs") == "trade-offs"
    assert _slugify_for_filename("12. Advanced Topics") == "advanced-topics"


def test_slugify_for_filename_strips_chapter_prefix():
    assert _slugify_for_filename("Chapter 3: Testing") == "testing"


def test_slugify_for_filename_strips_russian_prefix():
    result = _slugify_for_filename("Глава 5. Название")
    assert "название" in result


def test_chapter_filename():
    assert chapter_filename("1. Trade-Offs", 0) == "01 - trade-offs"
    assert chapter_filename("Testing", 9) == "10 - testing"


def test_roundtrip_apkg():
    """Write cards to .apkg, read them back, verify they match."""
    cards = [
        Card(question="What is X?", answer="X is Y.", chapter_title="Ch 1", book_title="Test Book"),
        Card(question="Why Z?", answer="Because W.", chapter_title="Ch 1", book_title="Test Book"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = package_single_chapter(
            cards, "Test Book", 0, tmpdir, model_version="gpt-5.5",
        )
        assert os.path.exists(path)
        loaded = _read_cards_from_apkg(path)
        assert len(loaded) == 2
        assert loaded[0].question == "What is X?"
        assert loaded[1].answer == "Because W."
        assert loaded[0].book_title == "Test Book"
        assert "model::gpt-5.5" in loaded[0].tags
        assert all("model::gpt-5.5" in tags for tags in _note_tags(path))


def test_package_preserves_existing_model_tag():
    cards = [
        Card(
            question="Q",
            answer="A",
            chapter_title="Ch",
            book_title="Book",
            tags=["book::book", "model::cli::claude-opus-4-8"],
        ),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = package_single_chapter(
            cards, "Book", 0, tmpdir, model_version="gpt-5.5",
        )
        tags = _note_tags(path)[0]
        assert "model::cli::claude-opus-4-8" in tags
        assert "model::gpt-5.5" not in tags


def test_load_existing_chapters():
    cards_ch1 = [
        Card(question="Q1", answer="A1", chapter_title="Chapter 1", book_title="Book"),
    ]
    cards_ch2 = [
        Card(question="Q2", answer="A2", chapter_title="Chapter 2", book_title="Book"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        package_single_chapter(cards_ch1, "Book", 0, tmpdir)
        package_single_chapter(cards_ch2, "Book", 1, tmpdir)
        existing = load_existing_chapters(tmpdir)
        assert 0 in existing
        assert 1 in existing
        assert len(existing[0]) == 1
        assert existing[0][0].question == "Q1"


def test_package_cards_preserves_original_chapter_numbers_and_order():
    cards = [
        Card(question="Q6", answer="A6", chapter_title="Six", book_title="Book"),
        Card(question="Q5", answer="A5", chapter_title="Five", book_title="Book"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "combined.apkg")
        package_cards(
            cards,
            "Book",
            out,
            chapter_order={"Five": 4, "Six": 5},
        )

        assert _deck_names(out) == [
            "Book::05 - Five",
            "Book::06 - Six",
        ]


def test_package_practice_preserves_original_chapter_numbers_and_order():
    cards = [
        Card(question="Q6", answer="A6", chapter_title="Six", book_title="Book"),
        Card(question="Q5", answer="A5", chapter_title="Five", book_title="Book"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "practice.apkg")
        package_practice(
            cards,
            "Practice | Book",
            out,
            chapter_order={"Five": 4, "Six": 5},
        )

        assert _deck_names(out) == [
            "Practice | Book::05 - Five",
            "Practice | Book::06 - Six",
        ]


def test_package_practice_subdecks_match_per_chapter_filenames():
    """The combined deck and the per-chapter file must agree on the number."""
    cards = [Card(question="Q", answer="A", chapter_title="Five", book_title="Book")]
    with tempfile.TemporaryDirectory() as tmpdir:
        combined = os.path.join(tmpdir, "practice.apkg")
        package_practice(
            cards, "Practice | Book", combined, chapter_order={"Five": 4},
        )
        chapter_path = package_practice_chapter(
            cards, "Practice | Book", 4, os.path.join(tmpdir, "chapters"),
        )

        assert _deck_names(combined) == ["Practice | Book::05 - Five"]
        assert _deck_names(chapter_path) == ["Practice | Book::05 - Five"]
        assert os.path.basename(chapter_path).startswith("05 - ")


def test_package_practice_falls_back_to_first_appearance_order():
    cards = [
        Card(question="Q1", answer="A1", chapter_title="Alpha", book_title="Book"),
        Card(question="Q2", answer="A2", chapter_title="Beta", book_title="Book"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "practice.apkg")
        package_practice(cards, "Practice | Book", out)

        assert _deck_names(out) == [
            "Practice | Book::01 - Alpha",
            "Practice | Book::02 - Beta",
        ]


def _note_types(path: str) -> list[tuple[str, int]]:
    """(note type name, Anki model type) per note; model type 1 means cloze."""
    with zipfile.ZipFile(path, "r") as zf:
        db_name = next(n for n in zf.namelist() if n.startswith("collection.anki2"))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(zf.read(db_name))
            tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        models = json.loads(conn.execute("SELECT models FROM col").fetchone()[0])
        rows = conn.execute("SELECT mid FROM notes ORDER BY id").fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)
    return [(models[str(mid)]["name"], models[str(mid)]["type"]) for (mid,) in rows]


def _card_count(path: str) -> int:
    with zipfile.ZipFile(path, "r") as zf:
        db_name = next(n for n in zf.namelist() if n.startswith("collection.anki2"))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(zf.read(db_name))
            tmp_path = tmp.name
    try:
        conn = sqlite3.connect(tmp_path)
        n = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
        conn.close()
    finally:
        os.unlink(tmp_path)
    return int(n)


def _mixed_cards() -> list[Card]:
    return [
        Card(question="What is tardive dysphoria?", answer="A drug-induced state.",
             chapter_title="Ch", book_title="Book"),
        Card(question="The result is {{c1::tardive dysphoria}}.", answer="Gloss",
             chapter_title="Ch", book_title="Book"),
    ]


def test_cloze_cards_use_the_cloze_note_type():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "mixed.apkg")
        package_cards(_mixed_cards(), "Book", out)

        assert _note_types(out) == [
            ("book2anki Basic", 0),
            ("book2anki Cloze", 1),
        ]
        # One deletion per note, so one Anki card per note.
        assert _card_count(out) == 2


def test_cloze_deletion_survives_field_escaping():
    cards = [Card(question="A <b>bold</b> claim & {{c1::the term}} here.",
                  answer="g", chapter_title="Ch", book_title="Book")]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "cloze.apkg")
        package_cards(cards, "Book", out)

        text = _read_cards_from_apkg(out)[0].question
        assert "{{c1::the term}}" in text
        assert "<b>bold</b>" in text
        assert "&amp;" in text


def test_mixed_deck_round_trips_through_resume():
    """Resume reads chapters back from disk; the note type must not be lost."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chapters_dir = os.path.join(tmpdir, "chapters")
        package_single_chapter(_mixed_cards(), "Book", 0, chapters_dir)

        resumed = load_existing_chapters(chapters_dir)[0]
        assert [is_cloze(c) for c in resumed] == [False, True]

        # And again, so a twice-resumed run still packages the right note types.
        out = os.path.join(tmpdir, "again.apkg")
        package_cards(resumed, "Book", out)
        assert _note_types(out) == [
            ("book2anki Basic", 0),
            ("book2anki Cloze", 1),
        ]


def test_cloze_note_type_matches_basic_field_layout():
    """Same fields in the same order, so _read_cards_from_apkg needs no branch."""
    assert (
        [f["name"] for f in CLOZE_MODEL.fields]
        == [f["name"] for f in CARD_MODEL.fields]
    )


def test_load_existing_chapters_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert load_existing_chapters(tmpdir) == {}


def test_load_existing_chapters_nonexistent_dir():
    assert load_existing_chapters("/nonexistent/path") == {}


def test_gap_context_blanks_bolded_word():
    assert (
        _gap_context("She had to <b>come to grips with</b> the new reality.")
        == "She had to <b>_____</b> the new reality."
    )


def test_gap_context_no_bold_returns_empty():
    assert _gap_context("no highlighted word here") == ""
    assert _gap_context("") == ""


def test_split_etymology_separates_bundled_field():
    bundled = 'Present everywhere<div class="etymology">Latin ubique = everywhere</div>'
    definition, etymology = _split_etymology(bundled)
    assert definition == "Present everywhere"
    assert etymology == "Latin ubique = everywhere"


def test_split_etymology_no_etymology():
    assert _split_etymology("Just a definition") == ("Just a definition", "")
    assert _split_etymology("") == ("", "")


def test_package_vocab_production_writes_valid_deck():
    cards = [
        Card(
            question="to come to grips with",
            answer="примириться с",
            chapter_title="Ch 1",
            book_title="Book",
            example="She had to <b>come to grips with</b> the new reality.",
            image="To begin to deal with something difficult",
            source_url="It took months to <b>come to grips with</b> the loss.",
        ),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "speak.apkg")
        package_vocab_production(cards, "Book C1 (speaking)", out)
        assert os.path.getsize(out) > 0
