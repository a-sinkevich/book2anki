import re
import json

from book2anki.prompts import (
    DEPTH_INSTRUCTIONS,
    PROPERTY_DEPTH_INSTRUCTIONS,
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


class TestBoldInAnswers:
    """Bold is allowed for scanning an answer; italic never is."""

    def test_answers_may_bold_the_key_term(self):
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "Bold the one term an answer turns on" in prompt
            assert "At most one span per answer" in prompt

    def test_questions_may_not(self):
        """Bold in a question points at what matters — the reader's job."""
        assert "Never in a question" in build_prompt("Book", "Ch", "text", 2, "en")

    def test_an_answer_that_is_only_a_term_gets_none(self):
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "already just a term or a one-line gloss" in prompt

    def test_italic_stays_banned_everywhere(self):
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en"),
                       build_prompt("V", "V", "t", 2, "en", is_transcript=True)):
            assert "No italics, ever" in prompt
            assert "do not use <em>, <i>" in prompt


def test_vocab_and_practice_prompts_have_no_term_cards():
    """Vocab is already production-direction; practice cards are exercises."""
    assert "PRODUCTION CARDS" not in build_practice_prompt("Book", "Ch", "text", 1)
    assert "PRODUCTION CARDS" not in build_prompt_request("Study X", 1, "en")


def test_cloze_must_quote_the_source_never_compose():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "quote it, never compose one" in prompt
    assert "Never write the sentence yourself" in prompt
    assert "never invent a sentence in order to make a cloze possible" in prompt


def test_transcripts_get_no_cloze_cards():
    """A speech-to-text transcript has no authored wording worth quoting."""
    prompt = build_prompt("Video", "Video", "text", 2, "en",
                          is_article=True, is_transcript=True)
    assert "PRODUCTION CARDS" in prompt    # the second card type is still wanted
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
    assert ("never add a concept card so that a production card has something to pair with"
            in prompt)
    assert "do not give every concept a name card" in prompt
    assert "ordered so each term card follows the concept card" not in prompt


class TestPropertyCards:
    """Cloze/reverse cards for the property a claim turns on, not just its name."""

    def test_absent_below_depth_2(self):
        """Depth 1 is told to leave distinctions out; these are distinctions."""
        for depth in (0, 1):
            prompt = build_prompt("Book", "Ch", "text", depth, "en")
            assert "DISTINGUISHING PROPERTY" not in prompt
            assert "A property card needs a contrast or a condition" not in prompt
            assert "Exactly one kind of missing piece qualifies" in prompt

    def test_present_from_depth_2(self):
        for depth in (2, 3):
            prompt = build_prompt("Book", "Ch", "text", depth, "en")
            assert "DISTINGUISHING PROPERTY" in prompt
            assert "Exactly two kinds of missing piece qualify" in prompt
            assert PROPERTY_DEPTH_INSTRUCTIONS[depth][:40] in prompt

    def test_the_span_must_be_short_enough_to_grade(self):
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "Hide a phrase, not a clause" in prompt
        assert "Drop anything you could not grade" in prompt

    def test_emphasis_is_a_hint_not_a_licence(self):
        """The parsers now carry <em> through, but it marks three different things."""
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "Author emphasis is a hint, not a licence" in prompt
        assert "most emphasised phrases earn no card at all" in prompt

    def test_transcripts_get_the_rules_that_still_apply(self):
        """No cloze and no markup there, so two of the four rules are dead text."""
        prompt = build_prompt("Video", "Video", "text", 2, "en",
                              is_article=True, is_transcript=True)
        assert "A property card needs a contrast or a condition" in prompt
        assert "Drop anything you could not grade" in prompt
        assert "Hide a phrase, not a clause" not in prompt
        assert "Author emphasis is a hint" not in prompt

    def test_emphasis_markers_are_explained_but_not_to_be_copied(self):
        prompt = build_prompt("Book", "Ch", "text", 1, "en")
        assert "the author's own emphasis" in prompt
        assert "Strip it from everything you write, a quoted cloze sentence included" in prompt

    def test_they_do_not_get_their_own_depth_ladder_rung(self):
        """A property card is still bound by the depth instruction above it."""
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "adding production cards is not a reason to write more" in prompt
        assert "do not give every emphasised phrase a property card" in prompt


def test_reverse_question_form_is_labelled_for_counting():
    for kwargs in ({}, {"is_transcript": True}):
        prompt = build_prompt("S", "C", "text", 2, "en", **kwargs)
        assert 'Set "type": "term"' in prompt


class TestDepthLadder:
    """Each level must exclude what the next level adds, or it leaks upward.

    Depth 1 used to bar only "minor" supporting details while depth 2 added the
    "key"/"notable"/"important" ones, so important supporting material was
    excluded by neither level and drifted into depth 1 — worst on dense text,
    which has the most of it.
    """

    def test_depth_1_excludes_what_depth_2_adds(self):
        d1 = DEPTH_INSTRUCTIONS[1]
        assert "Leave out supporting evidence, examples, distinctions" in d1
        assert "including the important ones" in d1

    def test_depth_2_excludes_what_depth_3_adds(self):
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "Leave out specific data points, case studies" in d2

    def test_depth_2_treats_an_enumeration_as_an_idea(self):
        """DDIA lists five ways to find a service; depth 2 carded only two.

        Each entry read as a thin distinction or a named framework, which the
        exclusions above bar — but the set of options is the point of the
        section, and nothing told the model to see the set.
        """
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "the alternative ways of doing something, the set is an idea" in d2

    def test_depth_2_names_the_tools_people_reach_for(self):
        """Chapter 5 names 30 products; grouping by category is what keeps it sane."""
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "tools, databases or libraries" in d2
        assert "One such card per category" in d2
        assert "never a card per product" in d2

    def test_depth_2_makes_the_tool_names_the_answer(self):
        """"A single card per category" was read as one card for the whole list,
        so the names ended up as a clause inside a five-part answer — present,
        but never actually recalled.
        """
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "with the names as the answer" in d2
        assert "never only a passing mention inside some longer answer" in d2

    def test_depth_2_still_refuses_a_product_mentioned_in_passing(self):
        """73% of that chapter's product names appear once or twice."""
        assert "appears only as an aside still earns nothing" in DEPTH_INSTRUCTIONS[2]

    def test_only_depth_2_needs_the_enumeration_carve_out(self):
        """Depth 3 already takes everything; depth 0 and 1 must not widen."""
        for depth in (0, 1):
            assert "alternative ways of doing something" not in DEPTH_INSTRUCTIONS[depth]
            assert "tools, databases or libraries" not in DEPTH_INSTRUCTIONS[depth]

    def test_no_depth_sets_a_card_quota(self):
        """Count follows the material; the level constrains kind, not quantity."""
        for depth, text in DEPTH_INSTRUCTIONS.items():
            assert not re.search(r"\b\d+\s*(-\s*\d+)?\s+cards\b", text), depth

    def test_depth_1_lets_density_drive_the_count(self):
        assert "Let the material decide how many" in DEPTH_INSTRUCTIONS[1]
