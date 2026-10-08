from book2anki.generator import (
    GENERATION_ATTEMPTS,
    _chapter_cards,
    LLMProvider,
    generation_errors,
    deduplicate as _deduplicate,
    deduplicate_vocab,
    generate_cards_for_prompt,
    _generate_with_retries,
    _generate_vocab_with_retries,
    _generate_idioms_with_retries,
    _parse_json_response,
    _split_into_chunks,
    vocab_word,
)
from book2anki.models import (
    ACTIVE_TAG, IDIOM_TAG, PASSIVE_TAG, Card, Chapter, is_cloze, is_typed,
)
from book2anki import generator

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


class TestPermanentFailures:
    """A wrong model or key is not a bad moment — retrying it just burns time."""

    @pytest.fixture(autouse=True)
    def _clean_state(self):
        generator._fatal_error = ""
        generation_errors.clear()
        yield
        generator._fatal_error = ""
        generation_errors.clear()

    def _run(self, provider, chapter="Chapter"):
        return _generate_with_retries(
            provider, "chapter text", "Book", chapter, 1, "en",
        )

    def test_missing_model_is_not_retried(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(
            RuntimeError("Error code: 404 - {'error': {'code': 'model_not_found'}}"),
            failures=99,
        )

        assert self._run(provider) == []
        assert provider.calls == 1

    def test_a_fatal_error_is_not_also_reported_per_chapter(self, monkeypatch):
        """It belongs to the account; the reporter prints it once for the run."""
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(
            RuntimeError("Error code: 404 - {'code': 'model_not_found'}"),
            failures=99,
        )

        self._run(provider)

        assert generation_errors == []
        assert "model_not_found" in generator.fatal_error()

    def test_a_rejected_request_is_not_retried_but_stays_local(self, monkeypatch):
        """A refused prompt dooms its own call, not the rest of the book."""
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(
            RuntimeError("Error code: 400 - invalid_request_error: too long"),
            failures=99,
        )

        assert self._run(provider) == []
        assert provider.calls == 1
        assert generator.fatal_error() == ""
        assert any("too long" in err for err in generation_errors)

    def test_later_chapters_are_skipped_without_calling_the_model(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(RuntimeError("Error code: 401 - invalid_api_key"),
                                  failures=99)

        self._run(provider, chapter="One")
        assert provider.calls == 1
        assert "invalid_api_key" in generator.fatal_error()

        assert self._run(provider, chapter="Two") == []
        assert provider.calls == 1  # never asked again

    def test_transient_errors_still_retry(self, monkeypatch):
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)
        provider = _FlakyProvider(RuntimeError("Error code: 503 - overloaded"),
                                  failures=99)

        assert self._run(provider) == []
        assert provider.calls == GENERATION_ATTEMPTS
        assert generator.fatal_error() == ""


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


class TestCommandCards:
    def _generate(self, *items):
        return _generate_with_retries(
            _FakeProvider([json.dumps(list(items))], "gpt-5.5"),
            "text", "Book", "Chapter", 1, "en", is_programming=True,
        )

    def test_a_command_is_tagged_and_kept_as_typed(self):
        cards = self._generate({
            "type": "command", "question": "(git) Show the last 3 commits, one line each",
            "answer": "git log --oneline -3", "example": "<pre><code>-3 last three</code></pre>",
        })

        assert is_typed(cards[0])
        assert cards[0].answer == "git log --oneline -3"
        assert cards[0].example == "<pre><code>-3 last three</code></pre>"

    def test_markup_and_prompt_sign_are_stripped_from_the_line(self):
        """Anki compares the typing with the text; markup would mark it wrong."""
        cards = self._generate({
            "type": "command", "question": "(shell) Run a and then b if it succeeded",
            "answer": "<code>$ a &amp;&amp; b</code>",
        })

        assert cards[0].answer == "a && b"

    def test_a_redirection_is_not_mistaken_for_a_tag(self):
        cards = self._generate({
            "type": "command", "question": "(shell) Sort in.txt into out.txt",
            "answer": "sort < in.txt > out.txt",
        })

        assert cards[0].answer == "sort < in.txt > out.txt"

    def test_a_multi_line_command_becomes_a_regular_card(self):
        """A one-line input box can't take it, so show the code instead."""
        cards = self._generate({
            "type": "command", "question": "(shell) Loop over the files",
            "answer": "for f in *; do\n  echo $f\ndone",
        })

        assert not is_typed(cards[0])
        assert cards[0].answer == "<pre><code>for f in *; do\n  echo $f\ndone</code></pre>"

    def test_a_deletion_wins_over_the_command_label(self):
        cards = self._generate({
            "type": "command", "question": "List files with {{c1::ls -la}}.", "answer": "g",
        })

        assert is_cloze(cards[0])
        assert not is_typed(cards[0])


class TestIdiomCards:
    def _generate(self, *items):
        return _generate_idioms_with_retries(
            _FakeProvider([json.dumps(list(items))], "gpt-5.5"),
            "text", "Book", "Chapter", 1,
        )

    _LOCK = "<pre><code>lock.lock();\ntry {\n    count++;\n} finally {\n    {{c1::lock.unlock();}}\n}</code></pre>"

    def test_a_snippet_is_a_typed_cloze_with_its_context_above(self):
        cards = self._generate({
            "type": "snippet", "context": "Guard a counter", "question": self._LOCK,
            "answer": "unlock in finally", "example": "",
        })

        assert is_cloze(cards[0]) and is_typed(cards[0])
        assert cards[0].tags == [IDIOM_TAG]
        assert cards[0].question == '<div class="cloze-context">Guard a counter</div>' + self._LOCK
        assert cards[0].answer == "unlock in finally"

    def test_a_line_is_typed_whole_and_kept_plain(self):
        cards = self._generate({
            "type": "line", "question": "Given <code>Map&lt;K, V&gt; m</code>…",
            "answer": "<code>m.computeIfAbsent(k, x -&gt; new ArrayList&lt;&gt;()).add(v);</code>",
        })

        assert is_typed(cards[0]) and not is_cloze(cards[0])
        assert cards[0].answer == "m.computeIfAbsent(k, x -> new ArrayList<>()).add(v);"

    @pytest.mark.parametrize("question", [
        "<pre><code>{{c1::if (x) {\n    y();}}\n}</code></pre>",       # spans lines
        "<pre><code>{{c1::while (!ready) {}}\n}</code></pre>",          # holds a brace
        "<pre><code>{{c1::a();}}\n{{c1::b();}}</code></pre>",           # number reused
        "<pre><code>lock.lock();</code></pre>",                         # nothing hidden
    ])
    def test_a_snippet_anki_cannot_ask_is_dropped(self, question):
        assert self._generate({"type": "snippet", "question": question, "answer": "g"}) == []

    def test_two_pieces_with_their_own_numbers_are_kept(self):
        question = (
            "<pre><code>pool.shutdown();\n"
            "if (!pool.{{c1::awaitTermination(30, TimeUnit.SECONDS)}}) {\n"
            "    {{c2::pool.shutdownNow();}}\n}</code></pre>"
        )
        cards = self._generate({"type": "snippet", "question": question, "answer": "g"})

        assert len(cards) == 1 and is_cloze(cards[0])

    def test_a_multi_line_line_becomes_a_regular_card(self):
        cards = self._generate({
            "type": "line", "question": "Lock and unlock", "answer": "lock.lock();\nlock.unlock();",
        })

        assert not is_typed(cards[0])
        assert cards[0].answer.startswith("<pre><code>")


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

    def test_a_reverse_question_restating_a_cloze_sentence_is_dropped(self):
        """Both run meaning -> answer, so the pair drills one piece twice."""
        reverse = Card(
            question="What is the fundamental rule for adding or removing fields in Avro?",
            answer="You may add or remove only a field that has a default value.",
            chapter_title="Ch", book_title="Book")
        cloze = Card(
            question='<div class="cloze-context">Avro schema evolution</div>'
                     "To maintain compatibility, you may add or remove only a field "
                     "that has {{c1::a default value}}.",
            answer="Avro's rule for compatible field changes.",
            chapter_title="Ch", book_title="Book")

        assert _deduplicate([reverse, cloze]) == [reverse]
        assert _deduplicate([cloze, reverse]) == [cloze]

    def test_a_concept_card_explaining_the_same_fact_survives(self):
        """A concept card's answer explains rather than restating the sentence."""
        concept = Card(
            question="In Avro, which compatibility breaks when a field is added "
                     "without a default value?",
            answer="Adding a field without a default breaks backward compatibility "
                   "(new readers cannot fill it in for old data), and removing one "
                   "breaks forward compatibility.",
            chapter_title="Ch", book_title="Book")
        cloze = Card(
            question="To maintain compatibility, you may add or remove only a field "
                     "that has {{c1::a default value}}.",
            answer="gloss", chapter_title="Ch", book_title="Book")

        assert len(_deduplicate([concept, cloze])) == 2

    def test_exact_duplicate(self):
        cards = [_card("What is X?"), _card("What is X?")]
        result = _deduplicate(cards)
        assert len(result) == 1


class TestChapterCards:
    class _Bar:
        def set_postfix_str(self, msg, refresh=False):
            pass

    @pytest.fixture(autouse=True)
    def _no_chunk_pause(self, monkeypatch):
        """Sequential chunks sleep CHUNK_PAUSE_SECONDS between calls."""
        monkeypatch.setattr("book2anki.generator.time.sleep", lambda _s: None)

    def _run(self, text, max_chars, produce):
        return _chapter_cards(
            Chapter(title="Ch", text=text, index=0), max_chars,
            produce, _deduplicate, self._Bar(), None, False,
        )

    def test_a_chapter_that_fits_in_one_chunk_is_still_deduplicated(self):
        """One model call repeats itself too; this path used to skip dedup."""
        result = self._run("short text", 1000,
                           lambda _t, _s: [_card("What is X?"), _card("What is X?")])

        assert len(result) == 1

    def test_a_split_chapter_is_deduplicated_across_chunks(self):
        result = self._run("word " * 400, 200,
                           lambda _t, _s: [_card("What is X?")])

        assert len(result) == 1

    def test_blank_cards_are_dropped(self):
        result = self._run("short text", 1000,
                           lambda _t, _s: [_card("Real?"), _card("   ")])

        assert [c.question for c in result] == ["Real?"]

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


class TestVocabUsage:
    def _parse(self, items: list[dict]) -> list[Card]:
        provider = _FakeProvider([json.dumps(items)], "gpt-5.5")
        return _generate_vocab_with_retries(
            provider, "text", "Book", "Chapter", "C1", "Russian",
        )

    def test_passive_word_is_tagged_and_labelled(self):
        [card] = self._parse([{
            "word": "susurrus", "pronunciation": "/sjuːˈsʌrəs/",
            "translation": "шелест", "usage": "passive", "register": "literary",
        }])
        assert card.tags == [PASSIVE_TAG]
        assert '<div class="register">literary</div>' in card.question
        assert vocab_word(card.question) == "susurrus"

    def test_anything_but_passive_is_active(self):
        cards = self._parse([
            {"word": "ubiquitous", "translation": "вездесущий", "usage": "active"},
            {"word": "to traipse", "translation": "таскаться"},
            {"word": "to mull", "translation": "обдумывать", "usage": "sometimes"},
        ])
        assert [c.tags for c in cards] == [[ACTIVE_TAG]] * 3
        assert all("register" not in c.question for c in cards)
