import pytest

from book2anki.cli import _use_single_deck, _write_output, parse_chapters
from book2anki.models import Card


class TestParseChapters:
    def test_single_number(self):
        assert parse_chapters("3") == [3]

    def test_comma_separated(self):
        assert parse_chapters("1,2,5") == [1, 2, 5]

    def test_range(self):
        assert parse_chapters("3-6") == [3, 4, 5, 6]

    def test_mixed(self):
        assert parse_chapters("1,3-5,8") == [1, 3, 4, 5, 8]

    def test_complex(self):
        assert parse_chapters("1,2,5-9,12") == [1, 2, 5, 6, 7, 8, 9, 12]

    def test_single_range(self):
        assert parse_chapters("1-1") == [1]

    def test_sorted_and_deduped(self):
        assert parse_chapters("5,3,1,3-5") == [1, 3, 4, 5]

    def test_spaces_stripped(self):
        assert parse_chapters("1, 3, 5-7") == [1, 3, 5, 6, 7]

    def test_invalid_not_a_number(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_chapters("abc")

    def test_invalid_range_reversed(self):
        with pytest.raises(ValueError, match="Invalid range"):
            parse_chapters("5-3")

    def test_invalid_zero(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            parse_chapters("0")

    def test_invalid_negative(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_chapters("-1")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_chapters("")


class TestSingleDeckMode:
    def test_depth_zero_does_not_imply_single_deck(self):
        assert not _use_single_deck(topic=None, flat=False)

    def test_flat_flag_uses_single_deck(self):
        assert _use_single_deck(topic=None, flat=True)

    def test_topic_uses_single_deck(self):
        assert _use_single_deck(topic="agriculture", flat=False)


def test_write_output_creates_combined_deck_for_chapter_subset(tmp_path):
    cards = [
        Card(
            question="Q",
            answer="A",
            chapter_title="Chapter 3",
            book_title="Book",
        ),
    ]

    output_dir = tmp_path / "Book"
    _write_output(
        cards,
        "Book",
        str(output_dir),
    )

    assert (output_dir / "Book.apkg").exists()
