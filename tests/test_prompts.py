import json

from book2anki.prompts import (
    DEPTH_INSTRUCTIONS,
    TERM_DEPTH_INSTRUCTIONS,
    build_practice_prompt,
    build_prompt,
    build_prompt_request,
)


def test_build_prompt_contains_book_title():
    prompt = build_prompt("My Book", "Chapter 1", "Some text", 1, "en")
    assert "My Book" in prompt
    assert "Chapter 1" in prompt


def test_build_prompt_contains_chapter_text():
    prompt = build_prompt("Book", "Ch", "The actual content here", 1, "en")
    assert "The actual content here" in prompt


def test_build_prompt_contains_depth_instruction():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "core ideas" in prompt


def test_build_prompt_all_depths():
    for depth in (0, 1, 2, 3):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert DEPTH_INSTRUCTIONS[depth][:20] in prompt


def test_build_prompt_language():
    prompt = build_prompt("Book", "Ch", "text", 1, "ru")
    assert "ru" in prompt


def test_depth_zero_does_not_force_fixed_card_count():
    prompt = build_prompt("Book", "Ch", "text", 0, "en")
    assert "Do not aim for a fixed number of cards" in prompt
    assert "as many or as few as the content warrants" in prompt
    assert "2-3 cards" not in prompt


def test_build_prompt_pushes_examples_as_standalone_learning_material():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "standalone learning material" in prompt
    assert "For every non-trivial concept" in prompt
    assert "broader knowledge" in prompt
    assert "empty string only for atomic facts" in prompt


def test_programming_prompt_pushes_code_examples():
    prompt = build_prompt("Book", "Ch", "text", 1, "en", is_programming=True)
    assert "For every non-trivial programming concept" in prompt
    assert "minimal code snippet" in prompt
    assert "<pre><code>...</code></pre>" in prompt


def test_build_prompt_request_uses_study_request_without_source():
    prompt = build_prompt_request("Cognitive load theory for software engineers", 1, "en")
    assert "Study request" in prompt
    assert "Cognitive load theory for software engineers" in prompt
    assert "Use your broader knowledge" in prompt
    assert "standalone learning material" in prompt
    assert "concise deck title" in prompt
    assert '"title" and "cards" fields' in prompt


def test_practice_prompt_prefers_runnable_java_examples():
    prompt = build_practice_prompt(
        "Effective Java",
        "Concurrency",
        "Use concurrent collections.",
        1,
        code_lang="java",
    )

    assert "Runnable demonstrations" in prompt
    assert "public static void main(String[] args)" in prompt
    assert "complete single-file Java 17+ example" in prompt
    assert "ExecutorService" in prompt
    assert "CountDownLatch" in prompt
    assert "Question names define the production API" in prompt
    assert "Do not add names like Demo, Example, Runner, App, or Test" in prompt
    assert "main method is only a learning/debugging harness" in prompt
    assert "separate API block for signatures" in prompt
    assert "<pre><code>class LRUCache" in prompt
    assert "<ul>" in prompt
    assert "Avoid mixing normal prose and inline <code> heavily" in prompt

    sample_start = prompt.index("[\n")
    sample_end = prompt.index("\n]\n", sample_start) + 2
    sample_cards = json.loads(prompt[sample_start:sample_end])
    assert sample_cards[0]["question"].startswith(
        "<b>Implement a Builder for NutritionFacts</b>"
    )


def test_build_prompt_asks_for_term_cards_at_every_depth():
    for depth in (0, 1, 2, 3):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert TERM_DEPTH_INSTRUCTIONS[depth][:30] in prompt


def test_term_cards_show_literal_cloze_syntax():
    """The f-string braces must survive as a real {{c1::...}} example."""
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "{{c1::...}}" in prompt
    assert "{{c1::tardive dysphoria}}" in prompt
    # No stray single braces left over from escaping.
    assert "{c1::" not in prompt.replace("{{c1::", "")


def test_term_cards_keep_cloze_in_source_language():
    prompt = build_prompt("Book", "Ch", "text", 1, "ru")
    assert "Keep the cloze sentence in the language of the source text" in prompt
    assert 'Write "answer" and "context" in ru' in prompt


def test_term_cards_state_the_derivability_test():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "THE TEST every cloze must pass" in prompt
    assert "Passes:" in prompt and "Fails:" in prompt


def test_term_cards_forbid_multiple_deletions():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "Never c2, c3, or multiple deletions" in prompt


def test_output_contract_mentions_type_and_context():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert '"type" and "context"' in prompt


def test_vocab_and_practice_prompts_have_no_term_cards():
    """Vocab is already production-direction; practice cards are exercises."""
    assert "TERM CARDS" not in build_practice_prompt("Book", "Ch", "text", 1)
    assert "TERM CARDS" not in build_prompt_request("Study X", 1, "en")


def test_cloze_must_quote_the_source_never_compose():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "quote it, never compose one" in prompt
    assert "Never write the sentence yourself" in prompt
    assert "never invent a sentence in order to make a cloze possible" in prompt


def test_transcripts_get_no_cloze_cards():
    """A speech-to-text transcript has no authored wording worth quoting."""
    prompt = build_prompt("Video", "Video", "text", 2, "en",
                          is_article=True, is_transcript=True)
    assert "TERM CARDS" in prompt          # term cards still wanted
    assert 'Do NOT emit any card with "type": "cloze"' in prompt
    assert "Form 1 — cloze" not in prompt
    assert "THE TEST every cloze must pass" not in prompt


def test_non_transcript_sources_keep_cloze():
    for kwargs in ({}, {"is_article": True}):
        prompt = build_prompt("S", "C", "text", 2, "en", **kwargs)
        assert "Form 1 — cloze (preferred)" in prompt
        assert 'Do NOT emit any card with "type": "cloze"' not in prompt


def test_term_cards_must_not_inflate_concept_card_count():
    """The ordering hint used to read as a one-concept-per-term requirement."""
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "The depth instruction alone decides how many of those to write" in prompt
    assert "never add a concept card so that a term card has something to pair with" in prompt
    assert "do not give every concept a term card" in prompt
    assert "ordered so each term card follows the concept card" not in prompt


def test_reverse_question_form_is_labelled_for_counting():
    for kwargs in ({}, {"is_transcript": True}):
        prompt = build_prompt("S", "C", "text", 2, "en", **kwargs)
        assert 'Set "type": "term"' in prompt
