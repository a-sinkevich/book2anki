from book2anki.generator import (
    GENERATION_ATTEMPTS,
    LLMProvider,
    generation_errors,
    deduplicate as _deduplicate,
    deduplicate_vocab,
    generate_cards_for_prompt,
    _generate_with_retries,
    _parse_json_response,
    _split_into_chunks,
    vocab_word,
)
from book2anki.models import Card, is_cloze

import json
import pytest


def _card(q: str, a: str = "answer") -> Card:
    return Card(question=q, answer=a, chapter_title="Ch", book_title="Book")


class _FakeProvider(LLMProvider):
    def __init__(self, responses: list[str], model: str) -> None:
        self.responses = responses
        self.model = model
        self.calls = 0

    def generate(self, prompt: str) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response

    def context_window_tokens(self) -> int:
        return 100_000

    def model_name(self) -> str:
        return self.model


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


class TestCliEmptyRetry:
    def test_cli_provider_retries_empty_card_result(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _seconds: None)
        provider = _FakeProvider(
            [
                "[]",
                '[{"question": "Q", "answer": "A"}]',
            ],
            "cli:claude-opus-5",
        )

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
        )

        assert provider.calls == 2
        assert [card.question for card in cards] == ["Q"]

    def test_api_provider_does_not_retry_empty_card_result(self):
        provider = _FakeProvider(
            [
                "[]",
                '[{"question": "Q", "answer": "A"}]',
            ],
            "gpt-5.5",
        )

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
        )

        assert provider.calls == 1
        assert cards == []


class _FlakyProvider(LLMProvider):
    """Fails the first `failures` calls, then answers with one card."""

    def __init__(self, error: Exception, failures: int, model: str = "gpt-5.5") -> None:
        self.error = error
        self.failures = failures
        self.model = model
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return '[{"question": "Q", "answer": "A"}]'

    def context_window_tokens(self) -> int:
        return 100_000

    def model_name(self) -> str:
        return self.model


class TestTransientFailureRetry:
    """API providers must retry transient failures, not just CLI ones."""

    def test_api_provider_retries_after_error(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(RuntimeError("Error code: 429 rate_limit"), failures=2)

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
        )

        assert provider.calls == 3
        assert [card.question for card in cards] == ["Q"]

    def test_api_provider_retries_unparseable_response(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FakeProvider(
            ["not json at all", '[{"question": "Q", "answer": "A"}]'],
            "gpt-5.5",
        )

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
        )

        assert provider.calls == 2
        assert [card.question for card in cards] == ["Q"]

    def test_gives_up_after_the_attempt_limit(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        generation_errors.clear()
        provider = _FlakyProvider(RuntimeError("nope"), failures=99)

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
        )

        assert provider.calls == GENERATION_ATTEMPTS
        assert cards == []
        assert any("nope" in err for err in generation_errors)
        generation_errors.clear()


class TestPromptGeneration:
    def test_generates_cards_from_prompt_request(self):
        provider = _FakeProvider(
            ['{"title": "Cognitive Load for Engineers", "cards": ['
             '{"question": "What is cognitive load?", "answer": "Mental effort.", '
             '"example": "A crowded API can increase extraneous load."}]}'],
            "gpt-5.5",
        )

        title, cards = generate_cards_for_prompt(
            provider,
            "Cognitive load theory for software engineers",
            "Prompt — Cognitive load theory",
            1,
            "en",
        )

        assert provider.calls == 1
        assert title == "Cognitive Load for Engineers"
        assert len(cards) == 1
        assert cards[0].book_title == "Cognitive Load for Engineers"
        assert cards[0].chapter_title == "Generated Study Guide"
        assert cards[0].source_url == "Cognitive load theory for software engineers"
        assert "source::prompt" in cards[0].tags

    def test_prompt_generation_falls_back_to_request_title_for_old_array_response(self):
        provider = _FakeProvider(
            ['[{"question": "Q", "answer": "A"}]'],
            "gpt-5.5",
        )

        title, cards = generate_cards_for_prompt(
            provider,
            "Long request",
            "Prompt — Long request",
            1,
            "en",
        )

        assert title == "Prompt — Long request"
        assert len(cards) == 1
        assert cards[0].book_title == "Prompt — Long request"

    def test_cli_provider_does_not_retry_topic_empty_result(self):
        provider = _FakeProvider(
            [
                "[]",
                '[{"question": "Q", "answer": "A"}]',
            ],
            "cli:claude-opus-5",
        )

        cards = _generate_with_retries(
            provider, "chapter text", "Book", "Chapter", 1, "en",
            topic="missing topic",
        )

        assert provider.calls == 1
        assert cards == []


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

    def test_overlap_larger_than_chunk_still_terminates(self):
        """A break point can land at max_chars // 2, so the overlap must be capped."""
        chunks = _split_into_chunks("word " * 2000, 3000, overlap_chars=2000)
        assert len(chunks) > 1
        assert "".join(chunks)  # completed rather than looping forever

    def test_overlap_exists(self):
        text = ("A" * 500 + "\n\n") * 10  # ~5020 chars with paragraph breaks
        chunks = _split_into_chunks(text, 2000, overlap_chars=200)
        if len(chunks) > 1:
            # Last part of chunk N should appear at start of chunk N+1
            end_of_first = chunks[0][-100:]
            assert end_of_first in chunks[1]


class TestClozeCards:
    def _generate(self, payload, **kwargs):
        return _generate_with_retries(
            _FakeProvider([payload], "gpt-5.5"),
            "text", "Book", "Chapter", 1, "ru", **kwargs,
        )

    def test_cloze_item_is_detected_and_kept_verbatim(self):
        cards = self._generate(json.dumps([{
            "type": "cloze",
            "question": "The result is {{c1::tardive dysphoria}}.",
            "answer": "Ухудшение депрессии.",
        }]))

        assert is_cloze(cards[0])
        assert cards[0].question == "The result is {{c1::tardive dysphoria}}."

    def test_context_is_rendered_above_the_sentence(self):
        cards = self._generate(json.dumps([{
            "type": "cloze",
            "question": "The result is {{c1::tardive dysphoria}}.",
            "answer": "gloss",
            "context": "Долгосрочный приём антидепрессантов",
        }]))

        assert cards[0].question == (
            '<div class="cloze-context">Долгосрочный приём антидепрессантов</div>'
            "The result is {{c1::tardive dysphoria}}."
        )

    def test_cloze_without_a_deletion_degrades_to_a_normal_card(self):
        """Anki generates no cards from a cloze note with no deletion in it."""
        cards = self._generate(json.dumps([{
            "type": "cloze",
            "question": "The result is tardive dysphoria.",
            "answer": "gloss",
        }]))

        assert not is_cloze(cards[0])
        assert cards[0].question == "The result is tardive dysphoria."

    def test_deletion_wins_over_a_missing_type_label(self):
        """Literal {{c1::...}} on a basic note would render as braces."""
        cards = self._generate(json.dumps([{
            "question": "The result is {{c1::tardive dysphoria}}.",
            "answer": "gloss",
        }]))

        assert is_cloze(cards[0])

    def test_transcripts_never_yield_cloze_cards(self):
        """A machine transcript has no authored wording to quote."""
        cards = self._generate(json.dumps([
            {"question": "What is X?", "answer": "A"},
            {"type": "cloze", "question": "He said {{c1::tardive dysphoria}} once.",
             "answer": "gloss"},
        ]), is_transcript=True)

        assert [c.question for c in cards] == ["What is X?"]

    def test_reverse_question_term_cards_are_plain_cards(self):
        """A term card with no deletion is a basic note like any other."""
        cards = self._generate(json.dumps([{
            "type": "term",
            "question": "What is the term for a drug-induced depressed state?",
            "answer": "Tardive dysphoria",
        }]))

        assert not is_cloze(cards[0])

    def test_no_card_type_carries_a_marker_tag(self):
        """The question text is the single source of truth for the note type."""
        cards = self._generate(json.dumps([
            {"question": "What is X?", "answer": "A"},
            {"type": "term", "question": "What is the term for X?", "answer": "Xitis"},
            {"type": "cloze", "question": "The result is {{c1::Xitis}}.", "answer": "gloss"},
        ]))

        assert [c.tags for c in cards] == [[], [], []]

    def test_term_and_concept_cards_survive_together(self):
        """The two directions are the point — dedup must not collapse them."""
        cards = self._generate(json.dumps([
            {"question": "What is tardive dysphoria?", "answer": "A drug-induced state."},
            {"type": "cloze", "question": "The result is {{c1::tardive dysphoria}}.",
             "answer": "gloss"},
        ]))

        assert len(_deduplicate(cards)) == 2


class TestDeduplicate:
    def test_cloze_cards_hiding_the_same_term_are_merged(self):
        cards = [
            Card(question="One sentence about {{c1::anchoring}}.", answer="a",
                 chapter_title="Ch", book_title="Book"),
            Card(question="A completely different sentence on {{c1::Anchoring}} here.",
                 answer="a", chapter_title="Ch", book_title="Book"),
        ]
        assert len(_deduplicate(cards)) == 1

    def test_cloze_cards_hiding_different_terms_are_kept(self):
        cards = [
            Card(question="A sentence about {{c1::anchoring}}.", answer="a",
                 chapter_title="Ch", book_title="Book"),
            Card(question="A sentence about {{c1::priming}}.", answer="a",
                 chapter_title="Ch", book_title="Book"),
        ]
        assert len(_deduplicate(cards)) == 2

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


def _vcard(word: str, context: str, ipa: str = "") -> Card:
    q = word + (f'<div class="ipa">{ipa}</div>' if ipa else "")
    return Card(
        question=q,
        answer="translation",
        chapter_title="Ch",
        book_title="Book",
        example=context,
        image="definition",
    )


class TestDeduplicateVocab:
    def test_same_word_same_spelling_merges(self):
        cards = [
            _vcard("to traipse", "She would <b>traipse</b> across the field."),
            _vcard("to traipse", "They <b>traipsed</b> home in the rain."),
        ]
        result = deduplicate_vocab(cards)
        assert len(result) == 1

    def test_spelling_variants_same_sentence_merge_to_correct(self):
        sentence = "He watched her <b>{}</b> across the muddy yard."
        cards = [
            _vcard("to trapess", sentence.format("traipse"), "/trəˈpɛs/"),
            _vcard("to traipse", sentence.format("traipse"), "/treɪps/"),
            _vcard("to trapesse", sentence.format("traipse"), "/trəˈpɛs/"),
            _vcard("to trapese", sentence.format("traipse"), "/trəˈpeɪz/"),
        ]
        result = deduplicate_vocab(cards)
        assert len(result) == 1
        # The correctly-spelled headword (matching the book's word) is kept.
        assert vocab_word(result[0].question) == "to traipse"

    def test_different_words_not_merged(self):
        cards = [
            _vcard("affect", "It did not <b>affect</b> the outcome."),
            _vcard("effect", "It had no <b>effect</b> on the outcome at all."),
        ]
        result = deduplicate_vocab(cards)
        assert len(result) == 2
