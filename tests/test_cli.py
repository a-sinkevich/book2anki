import pytest

from book2anki.cli import (
    _TBL_HEADER,
    _apkg_output_path,
    _create_provider,
    _prompt_deck_title,
    _use_single_deck,
    _write_output,
    parse_chapters,
)
from book2anki.models import Card, Chapter


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


def test_write_output_passes_original_chapter_order(monkeypatch, tmp_path):
    seen = {}

    def fake_package_cards(*_args, **kwargs):
        seen["chapter_order"] = kwargs["chapter_order"]

    monkeypatch.setattr("book2anki.cli.package_cards", fake_package_cards)

    _write_output(
        [
            Card(
                question="Q",
                answer="A",
                chapter_title="Chapter 5",
                book_title="Book",
            ),
        ],
        "Book",
        str(tmp_path / "Book"),
        chapters=[
            Chapter(title="Chapter 5", text="text", index=4),
            Chapter(title="Chapter 6", text="text", index=5),
        ],
    )

    assert seen["chapter_order"] == {"Chapter 5": 4, "Chapter 6": 5}


def test_prompt_deck_title_is_derived_from_request():
    title = _prompt_deck_title(
        "Fundamentals of cognitive load theory for software engineering practice",
    )
    assert title.startswith("Prompt — Fundamentals of cognitive load theory")


def test_apkg_output_path_accepts_file_or_directory():
    assert _apkg_output_path("Prompt — Cognitive Load", None) == (
        "Prompt_—_Cognitive_Load.apkg"
    )
    assert _apkg_output_path("Deck", "custom.apkg") == "custom.apkg"
    assert _apkg_output_path("Deck", "out") == "out/Deck.apkg"


def test_model_cli_prefix_routes_exact_model_to_claude_cli():
    provider = _create_provider("cli:claude-fable-5")
    assert provider.model_name() == "cli:claude-fable-5"


def test_model_cli_prefix_keeps_cli_aliases():
    provider = _create_provider("cli:opus")
    assert provider.model_name() == "cli:claude-opus-4-8"


def test_model_cli_prefix_requires_model_name():
    with pytest.raises(ValueError, match="requires a Claude CLI model name"):
        _create_provider("cli:")


def test_progress_table_does_not_show_cost_column():
    assert "Cost" not in _TBL_HEADER
