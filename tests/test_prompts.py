import re
import json

from book2anki.prompts import (
    DEPTH_INSTRUCTIONS,
    PRACTICE_DEPTH_INSTRUCTIONS,
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
    for depth in (0, 1, 2):
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
    for depth in (0, 1, 2):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert TERM_DEPTH_INSTRUCTIONS[depth][:30] in prompt


def test_term_cards_show_literal_cloze_syntax():
    """The f-string braces must survive as a real {{c1::...}} example."""
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert "{{c1::...}}" in prompt
    assert "{{c1::a default value}}" in prompt
    # No stray single braces left over from escaping.
    assert "{c1::" not in prompt.replace("{{c1::", "")


def test_term_cards_keep_cloze_in_source_language():
    prompt = build_prompt("Book", "Ch", "text", 2, "ru")
    assert "Keep the cloze sentence in the language of the source text" in prompt
    assert 'Write "answer" and "context" in ru' in prompt


def test_term_cards_state_the_derivability_test():
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert "THE TEST every cloze must pass" in prompt
    assert "Passes:" in prompt and "Fails:" in prompt


def test_term_cards_forbid_multiple_deletions():
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert "Never c2, c3, or multiple deletions" in prompt


def test_output_contract_mentions_type_and_context():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert '"type" and "context"' in prompt


class TestBoldInAnswers:
    """Bold is allowed for scanning an answer; italic never is."""

    def test_every_answer_gets_its_gist_bolded(self):
        """Off-by-default left most answers bare, and bold that shows up only
        sometimes can't be relied on: a reader checking the back still had to
        read every unmarked answer in full. The 89-of-124 failure that turned it
        off was the span landing on the question's own noun, which the span
        test below now rules out.
        """
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "Bold the gist of every answer" in prompt
            assert "a reader learns to look at the bold first" in prompt
            assert "Most answers need no bold at all" not in prompt
            assert "If you are unsure whether it helps, it does not" not in prompt

    def test_an_answer_that_is_its_own_gist_gets_none(self):
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "an answer that is already its own gist" in prompt
            assert "a term, a name, a number, or a phrase of a few words" in prompt

    def test_the_span_is_chosen_by_a_test_not_by_looking_termlike(self):
        """"The one term an answer turns on" got the most term-shaped noun bolded
        — "Each <b>leader</b> accepts writes locally without waiting for the
        others" — when the reader had supplied every word but that one.
        """
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "Choose the span by a test, not by what looks important" in prompt
            assert "cut the bolded words out, and the answer should stop answering" in prompt
            assert "enough for a reader who recalled the answer to confirm it" in prompt
            assert "usually a phrase rather than a single noun" in prompt

    def test_the_span_is_never_most_of_the_answer(self):
        """With bold on every answer, the new way to mark nothing is to mark it all."""
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "a few words, never most of the answer" in prompt
        full = build_prompt("Book", "Ch", "text", 2, "en")
        assert "most of the answer is bold, so the eye has nothing to land on" in full

    def test_a_contrast_is_marked_on_both_sides_or_neither(self):
        """"At most one span per answer" forced the model to bold one half of a
        two-sided contrast — "With <b>synchronous</b> replication ... with
        asynchronous replication ..." — leaving the other bare.
        """
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "the two sides of a contrast" in prompt
            assert "mark every part or none" in prompt
        full = build_prompt("Book", "Ch", "text", 2, "en")
        assert "only one side of the contrast is marked" in full

    def test_a_word_from_the_question_is_never_the_span(self):
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "never a word the question already contains" in prompt
            assert "the question already said leader" in prompt

    def test_only_the_answer_carries_bold(self):
        """Bold in a question points at what matters — the reader's job. In the
        example or a cloze it competes with the mark the reader looks for.
        """
        for prompt in (build_prompt("Book", "Ch", "text", 2, "en"),
                       build_prompt_request("Study X", 2, "en")):
            assert "never in a question" in prompt
            assert 'never in the "example" field' in prompt
        full = build_prompt("Book", "Ch", "text", 2, "en")
        assert "never in a cloze card, where Anki already highlights" in full

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
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert "quote it, never compose one" in prompt
    assert "Never write the sentence yourself" in prompt
    assert "never invent a sentence in order to make a cloze possible" in prompt


def test_transcripts_get_no_cloze_cards():
    """A speech-to-text transcript has no authored wording worth quoting."""
    prompt = build_prompt("Video", "Video", "text", 2, "en",
                          is_article=True, is_transcript=True)
    assert "PRODUCTION CARDS" in prompt    # the second card type is still wanted
    assert 'Do NOT emit any card with "type": "cloze"' in prompt
    assert "a cloze when the gap ends the sentence" not in prompt
    assert "THE TEST every cloze must pass" not in prompt


def test_non_transcript_sources_keep_cloze():
    for kwargs in ({}, {"is_article": True}):
        prompt = build_prompt("S", "C", "text", 2, "en", **kwargs)
        assert "a cloze when the gap ends the sentence" in prompt
        assert 'Do NOT emit any card with "type": "cloze"' not in prompt


def test_a_name_is_always_a_reverse_question():
    """The sentence defining a term opens with it, so a clozed name puts the gap
    first: "A {{c1::predicate lock}} works similarly to ..." makes the reader hold
    the whole sentence before filling it.
    """
    for depth in (0, 1, 2):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert "Never cloze a name" in prompt
        assert "What is the term for a lock that belongs to all objects" in prompt


def test_a_property_cloze_must_end_on_its_gap():
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert "The gap must close the sentence" in prompt
    assert "the gap opens the sentence — ask which fields" in prompt


def test_no_cloze_below_depth_2():
    """Only properties may be clozed, and they start at depth 2."""
    for depth in (0, 1):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert "Use one form only" in prompt
        assert '"type": "cloze"' not in prompt
        assert "Never write the sentence yourself" not in prompt


def test_cloze_drops_pointers_to_elsewhere_in_the_text():
    prompt = build_prompt("Book", "Ch", "text", 2, "en")
    assert 'drop a pointer to elsewhere in the text ("described earlier"' in prompt


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
        for depth in (2,):
            prompt = build_prompt("Book", "Ch", "text", depth, "en")
            assert "DISTINGUISHING PROPERTY" in prompt
            assert "Exactly two kinds of missing piece qualify" in prompt
            assert PROPERTY_DEPTH_INSTRUCTIONS[depth][:40] in prompt

    def test_a_two_sided_contrast_becomes_a_question_not_a_cloze(self):
        """"A property card needs a contrast" sent the model hunting for contrast
        sentences, and the tempting ones name both sides: "2PL provides
        {{c1::serializable isolation}}, whereas 2PC provides atomic commit"
        hands over half the pairing, which is the whole point of the card.
        """
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "a sentence naming BOTH sides of a contrast is not a cloze" in prompt
        assert "hiding either side hands the reader the other" in prompt
        assert "What is the difference between 2PL and 2PC?" in prompt

    def test_a_one_sided_statement_is_still_a_cloze(self):
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "Cloze only where the sentence states one side" in prompt
        assert "one side stated — nothing is handed over" in prompt

    def test_no_example_cloze_is_itself_a_two_sided_contrast(self):
        """The old gradeability example broke the rule now being added."""
        prompt = build_prompt("Book", "Ch", "text", 2, "en")
        assert "{{c1::requests}}, and forward compatibility on responses" not in prompt

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
    """Three rungs, each excluding what the next adds, and 2 is the top.

    Depth 3 was dropped: slow, expensive, and it produced far more cards than
    anyone reviews. Depth 2 inherited the job of being the most detailed pass,
    so its old exclusions — which all deferred to "a comprehensive pass" that
    no longer exists — were replaced by a test of its own.
    """

    def test_there_are_exactly_three_rungs(self):
        for table in (DEPTH_INSTRUCTIONS, TERM_DEPTH_INSTRUCTIONS,
                      PROPERTY_DEPTH_INSTRUCTIONS, PRACTICE_DEPTH_INSTRUCTIONS):
            assert sorted(table) == [0, 1, 2]

    def test_depth_1_excludes_what_depth_2_adds(self):
        d1 = DEPTH_INSTRUCTIONS[1]
        assert "Leave out supporting evidence, examples, distinctions" in d1
        assert "including the important ones" in d1

    def test_depth_2_is_defined_by_the_conversation_it_supports(self):
        """The old wording listed categories; this asks what the card is for."""
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "hold their own in a conversation" in d2
        assert "would not knowing this leave you unable to follow or take part" in d2

    def test_depth_2_no_longer_defers_to_a_pass_that_does_not_exist(self):
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "comprehensive pass covers those" not in d2
        assert "there is no more thorough pass to defer to" in d2

    def test_depth_2_states_what_never_comes_up(self):
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "the fine mechanics of how something works" in d2
        assert "unless the number is itself the point" in d2
        assert "asides about history or provenance" in d2

    def test_depth_2_treats_an_enumeration_as_an_idea(self):
        """DDIA lists five ways to find a service; depth 2 carded only two."""
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "the alternative ways of doing something, the set is an idea" in d2

    def test_the_names_go_in_one_card_beside_their_options(self):
        """Per-category tool cards gave 16 near-twin cards in one chapter, which
        interfere with each other in review even though none is a duplicate.
        """
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "ONE further card for the whole set" in d2
        assert "never a card per option and never one per name" in d2

    def test_the_names_are_the_answer(self):
        """Merging the roster away left the names only in concept answers, and
        often in the question, where they are handed over rather than recalled.
        """
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "with the names in the ANSWER and never in the question" in d2
        assert "a name you are handed in the question is a name you never have to recall" in d2

    def test_names_worth_nothing_are_named_as_such(self):
        d2 = DEPTH_INSTRUCTIONS[2]
        assert "ones any reader would know without this text" in d2
        assert "ones the text drops in passing" in d2

    def test_the_levels_are_not_written_for_technical_books(self):
        """They have to read the same for a history or psychology book."""
        for text in DEPTH_INSTRUCTIONS.values():
            for jargon in ("database", "code", "software", "engineer", "system"):
                assert jargon not in text.lower(), text

    def test_only_depth_2_needs_the_enumeration_carve_out(self):
        for depth in (0, 1):
            assert "alternative ways of doing something" not in DEPTH_INSTRUCTIONS[depth]

    def test_no_depth_sets_a_card_quota(self):
        """Count follows the material; the level constrains kind, not quantity."""
        for depth, text in DEPTH_INSTRUCTIONS.items():
            assert not re.search(r"\b\d+\s*(-\s*\d+)?\s+cards\b", text), depth

    def test_depth_1_lets_density_drive_the_count(self):
        assert "Let the material decide how many" in DEPTH_INSTRUCTIONS[1]
