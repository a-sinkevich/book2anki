from book2anki.generator import _deduplicate, _parse_json_response, _split_into_chunks
from book2anki.models import Card

import pytest


def _card(q: str, a: str = "answer") -> Card:
    return Card(question=q, answer=a, chapter_title="Ch", book_title="Book")


class TestParseJsonResponse:
    def test_plain_json(self):
        result = _parse_json_response('[{"question": "Q", "answer": "A"}]')
        assert len(result) == 1
        assert result[0]["question"] == "Q"

    def test_markdown_code_block(self):
        text = '```json\n[{"question": "Q", "answer": "A"}]\n```'
        result = _parse_json_response(text)
        assert len(result) == 1

    def test_surrounded_by_text(self):
        text = 'Here are the cards:\n[{"question": "Q", "answer": "A"}]\nDone!'
        result = _parse_json_response(text)
        assert len(result) == 1

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_json_response("not json at all")

    def test_multiple_cards(self):
        text = '[{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]'
        result = _parse_json_response(text)
        assert len(result) == 2


class TestSplitIntoChunks:
    def test_short_text_no_split(self):
        chunks = _split_into_chunks("short text", 100)
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_splits_long_text(self):
        text = "word " * 1000  # ~5000 chars
        chunks = _split_into_chunks(text, 2000, overlap_chars=200)
        assert len(chunks) > 1
        # All text should be covered
        for chunk in chunks:
            assert len(chunk) <= 2200  # max_chars + some tolerance for break point

    def test_overlap_exists(self):
        text = ("A" * 500 + "\n\n") * 10  # ~5020 chars with paragraph breaks
        chunks = _split_into_chunks(text, 2000, overlap_chars=200)
        if len(chunks) > 1:
            # Last part of chunk N should appear at start of chunk N+1
            end_of_first = chunks[0][-100:]
            assert end_of_first in chunks[1]


class TestDeduplicate:
    def test_no_duplicates(self):
        cards = [_card("What is photosynthesis?"), _card("How does gravity work?")]
        result = _deduplicate(cards)
        assert len(result) == 2

    def test_exact_duplicate(self):
        cards = [_card("What is X?"), _card("What is X?")]
        result = _deduplicate(cards)
        assert len(result) == 1

    def test_similar_duplicate(self):
        cards = [_card("What is X?"), _card("What is X")]
        result = _deduplicate(cards, threshold=0.8)
        assert len(result) == 1

    def test_different_enough(self):
        cards = [_card("What is photosynthesis?"), _card("What is mitosis?")]
        result = _deduplicate(cards, threshold=0.8)
        assert len(result) == 2

    def test_empty_list(self):
        assert _deduplicate([]) == []
