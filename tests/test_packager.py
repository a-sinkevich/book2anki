import os
import tempfile

from book2anki.models import Card
from book2anki.packager import (
    _read_cards_from_apkg,
    _slugify,
    _slugify_for_filename,
    _stable_id,
    chapter_filename,
    load_existing_chapters,
    package_single_chapter,
)


def test_stable_id_deterministic():
    assert _stable_id("hello") == _stable_id("hello")


def test_stable_id_different_inputs():
    assert _stable_id("hello") != _stable_id("world")


def test_slugify_basic():
    assert _slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    assert _slugify("Chapter 1: The Beginning!") == "chapter-1-the-beginning"


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
        path = package_single_chapter(cards, "Test Book", 0, tmpdir)
        assert os.path.exists(path)
        loaded = _read_cards_from_apkg(path)
        assert len(loaded) == 2
        assert loaded[0].question == "What is X?"
        assert loaded[1].answer == "Because W."
        assert loaded[0].book_title == "Test Book"


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


def test_load_existing_chapters_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert load_existing_chapters(tmpdir) == {}


def test_load_existing_chapters_nonexistent_dir():
    assert load_existing_chapters("/nonexistent/path") == {}
