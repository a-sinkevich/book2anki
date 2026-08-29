import pytest

from book2anki.cli import (
    _TBL_HEADER,
    _apkg_output_path,
    _chapter_order,
    _create_provider,
    _process_chapters,
    _prompt_deck_title,
    _use_single_deck,
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


def test_chapter_order_maps_titles_to_book_index():
    chapters = [
        Chapter(title="Chapter 5", text="text", index=4),
        Chapter(title="Chapter 6", text="text", index=5),
    ]
    assert _chapter_order(chapters) == {"Chapter 5": 4, "Chapter 6": 5}


def _chapters(*indexes: int) -> list[Chapter]:
    return [Chapter(title=f"Ch{i}", text="text", index=i) for i in indexes]


def _one_card(chapter: Chapter) -> Card:
    return Card(
        question=f"Q{chapter.index}", answer="A",
        chapter_title=chapter.title, book_title="Book",
    )


class TestProcessChapters:
    @pytest.mark.parametrize("parallel", [False, True])
    def test_returns_cards_in_book_order(self, parallel):
        chapters = _chapters(2, 0, 1)

        cards = _process_chapters(
            chapters, lambda ch, _bar, _cb: [_one_card(ch)], parallel,
        )

        assert [c.question for c in cards] == ["Q0", "Q1", "Q2"]

    def test_saves_each_chapter_as_it_lands(self):
        saved: list[int] = []

        _process_chapters(
            _chapters(0, 1), lambda ch, _bar, _cb: [_one_card(ch)], False,
            on_done=lambda ch, _cards: saved.append(ch.index),
        )

        assert saved == [0, 1]

    def test_empty_chapter_is_not_saved(self):
        saved: list[int] = []

        cards = _process_chapters(
            _chapters(0), lambda _ch, _bar, _cb: [], False,
            on_done=lambda ch, _cards: saved.append(ch.index),
        )

        assert cards == []
        assert saved == []

    def test_failing_chapter_is_reported_after_the_table_and_others_still_run(
        self, capsys,
    ):
        def run(chapter, _bar, _cb):
            if chapter.index == 0:
                raise RuntimeError("boom")
            return [_one_card(chapter)]

        cards = _process_chapters(_chapters(0, 1), run, parallel=True)

        assert [c.question for c in cards] == ["Q1"]
        # Reported once the live table has released the terminal, not mid-render.
        err = capsys.readouterr().err
        assert "boom" in err
        assert err.index("Problems during generation") > err.index("Total")


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
    assert provider.model_name() == "cli:claude-opus-5"


def test_model_cli_prefix_requires_model_name():
    with pytest.raises(ValueError, match="requires a Claude CLI model name"):
        _create_provider("cli:")


def test_progress_table_does_not_show_cost_column():
    assert "Cost" not in _TBL_HEADER
