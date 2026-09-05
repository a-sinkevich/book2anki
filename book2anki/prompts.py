import re

DEPTH_INSTRUCTIONS = {
    0: (
        "Generate cards only for the single most important ideas worth remembering long-term: "
        "the main thesis, core mental model, or essential conclusion. "
        "Do not aim for a fixed number of cards; create as many or as few as the content warrants, "
        "including zero for sections without substantive ideas. This is a minimal summary, not a study guide."
    ),
    1: (
        "Generate cards that test understanding of the chapter's core ideas: "
        "the main thesis, key arguments, and central takeaways. "
        "Leave out supporting evidence, examples, distinctions and secondary arguments — "
        "including the important ones, which belong to a more detailed pass — and never "
        "add a card merely because the chapter names or mentions something. "
        "Let the material decide how many cards that is: a dense chapter genuinely has "
        "more core ideas than a thin one. But every card must be one of those ideas, "
        "not a detail that arrived alongside one."
    ),
    2: (
        "Generate cards that test understanding of core ideas plus important supporting material: "
        "key evidence, notable examples, important distinctions, and secondary arguments. "
        "Leave out specific data points, case studies, named frameworks and quotes unless "
        "each carries an idea of its own — a comprehensive pass covers those. "
        "Skip minor details and tangential asides. "
        "But where the text lays out the alternative ways of doing something, the set is an "
        "idea in its own right: cover what the options are and what separates them, even where "
        "one option is thin taken alone. A product named in passing is still not a card."
    ),
    3: (
        "Generate cards that test thorough understanding of the chapter: "
        "core ideas, supporting evidence, specific data points, case studies, "
        "named frameworks, important quotes, and all significant details."
    ),
}

# How many terms are worth recalling *by name* at each depth. Depth 0 is a
# minimal summary, so it earns a term card only for the one idea the section is
# built around.
TERM_DEPTH_INSTRUCTIONS = {
    0: (
        "Only if the single central idea of this text has a proper name, add one term card "
        "for that name. Otherwise add none."
    ),
    1: (
        "Add term cards only for names central to the text's argument — the terms a reader "
        "would need to use to discuss it. Skip passing jargon."
    ),
    2: (
        "Add term cards for the central names plus important secondary terminology, "
        "named studies, effects, and key dates or quantities."
    ),
    3: (
        "Add term cards for every named concept, coined term, principle, law, effect, "
        "syndrome, framework, study, date, and quantity worth recalling by name."
    ),
}


# Distinguishing properties are supporting material by the depth ladder — depth 1
# is told in so many words to leave distinctions out — so these cards start at
# depth 2, where the concept cards covering the same material start. An empty
# string drops the whole category from the prompt.
PROPERTY_DEPTH_INSTRUCTIONS = {
    0: "",
    1: "",
    2: (
        "Add property cards for the distinctions the chapter's argument turns on: what "
        "separates two approaches it compares, and the conditions it gives for when a "
        "result holds. Skip distinctions the text draws only in passing."
    ),
    3: (
        "Add property cards for every distinction and condition worth recalling, "
        "including secondary comparisons and the qualifications attached to a claim."
    ),
}


_REVERSE_FORM_BODY = """Set "type": "term". The question describes everything \
except the missing piece; the answer is that piece and nothing else.

  {"type": "term", "question": "What is the term for depression caused by the long-term \
use of the antidepressants meant to treat it?", "answer": "Tardive dysphoria"}"""

_REVERSE_PROPERTY_EXAMPLE = """
  {"type": "term", "question": "Sparse indexes save memory over dense ones — at the \
cost of what?", "answer": "A short scan of the segment after the nearest indexed key"}"""


def _term_cards_section(
    depth: int, language: str, quote_source: bool = True,
) -> str:
    """Instructions for production-direction cards: retrieve, don't recognise.

    The cards produced by the main instructions run question → answer, and they
    routinely name the retrievable part inside the question. These run the other
    way: given everything else, produce the missing piece. Two kinds of piece
    qualify — a name, and (from depth 2) the property a claim turns on. Both
    directions have to be trained separately: understanding an idea perfectly is
    no guarantee of being able to retrieve what it is called or what it hinges on.

    Cloze cards quote the source verbatim, so `quote_source` is False for sources
    that are not authored prose (speech-to-text transcripts): those get reverse
    questions only, rather than cards built on a machine transcription.
    """
    property_depth = PROPERTY_DEPTH_INSTRUCTIONS[depth]
    if quote_source:
        forms = f"""Use whichever of these two forms fits the source text:

**Form 1 — cloze (preferred).** Set "type": "cloze". Take a sentence from the source \
text above — quote it, never compose one — wrap the missing piece in {{{{c1::...}}}}, and \
put a one-line gloss in "answer".

  THE TEST every cloze must pass: a reader who understands the material but has \
forgotten this particular piece must be able to recover it from the words that remain — \
and a reader who does not understand the material must not be able to guess it. If the \
rest of the sentence does not pin the answer down, the card only teaches the sentence. \
Use Form 2 instead.

  Passes: "When long-term antidepressant use itself produces a chronic, \
treatment-resistant depressed state, the result is {{{{c1::tardive dysphoria}}}}."
  Fails:  "Healy argues that {{{{c1::tardive dysphoria}}}} is a serious concern." \
(nothing left to derive the term from — this only drills the sentence)

**Form 2 — reverse question.** {_REVERSE_FORM_BODY}\
{_REVERSE_PROPERTY_EXAMPLE if property_depth else ""}

  Use Form 2 whenever the text has no sentence that passes the test."""

        cloze_rules = f"""
- **Never write the sentence yourself.** The cloze sentence is always the author's own, \
copied from the source text above. You may resolve a pronoun or back-reference so it \
stands alone ("it" → the thing itself, "this approach" → the named approach) and drop a \
trailing clause that depends on earlier text. Nothing beyond that: no rephrasing, no \
stitching two sentences together, no claims the text does not make, and nothing drawn \
from your own knowledge of the subject. If no sentence in the text works, use Form 2 — \
never invent a sentence in order to make a cloze possible
- **Keep the cloze sentence in the language of the source text**, always — even though \
the other cards are written in {language}. The hidden answer IS the source's own \
wording, so translating the sentence would destroy the card. Write "answer" and \
"context" in {language}
- **Exactly one {{{{c1::...}}}} per card.** Never c2, c3, or multiple deletions. Hide the \
missing piece only, never the surrounding words that make it derivable
- **"context" field**: a short orienting phrase in {language} (3-8 words) naming what \
the sentence is about, for sentences that read as ambiguous on their own. It must NEVER \
contain the hidden words or a translation of them, or the card gives itself away. Leave \
it empty when the sentence already stands alone
- **Answer side of a cloze**: a one-line gloss in {language}. Do not restate the whole \
sentence"""
    else:
        forms = f"""This source is a speech-to-text transcript rather than authored prose, so it \
holds no wording worth quoting verbatim. Use one form only:

**Reverse question.** {_REVERSE_FORM_BODY}

Do NOT emit any card with "type": "cloze" for this source, and do not write a sentence \
of your own to cloze — a transcript's phrasing is a machine's approximation of what was \
said, and quoting it would bake transcription errors into the answer."""

        cloze_rules = ""

    return f"""

PRODUCTION CARDS (second card type — retrieve it, don't just recognise it)

The cards described above hand you the answer's subject inside the question. Also \
generate cards for the other direction: given everything else, produce the missing \
piece. Recognising something and retrieving it are separate skills, and the retrievable \
part is the one that goes missing.

{_targets_section(property_depth)}

These are an ADDITION to the cards above and change nothing about them. The depth \
instruction alone decides how many of those to write — adding production cards is not a \
reason to write more. In particular: never add a concept card so that a production card \
has something to pair with, do not give every concept a name card, and do not give \
every emphasised phrase a property card.

{TERM_DEPTH_INSTRUCTIONS[depth]}{f" {property_depth}" if property_depth else ""}

{forms}

Rules for production cards:{cloze_rules}
- **A reverse question is written in {language}, but a name in its answer keeps the \
source's own spelling** — do not translate the term itself
- **One card per missing piece.** Do not build several cards testing the same name or \
the same property
- **Only what is worth retrieving.** A name card earns its place when the name is the \
thing you would forget. Skip everyday words, and skip terms the text merely mentions \
without explaining{_property_rules(property_depth, quote_source)}"""


def _targets_section(property_depth: str) -> str:
    """The kinds of missing piece a production card may test."""
    name_target = """Exactly one kind of missing piece qualifies, and nothing else does:

  A NAME — what the thing is called."""
    if not property_depth:
        return name_target
    return """Exactly two kinds of missing piece qualify, and nothing else does:

  1. A NAME — what the thing is called.
  2. A DISTINGUISHING PROPERTY — the specific thing a claim turns on: which case a \
technique suits, what separates two approaches the text compares, the condition under \
which a result holds."""


def _property_rules(property_depth: str, quote_source: bool) -> str:
    """Eligibility rules that keep property cards from swallowing every sentence.

    The two rules about the deleted span and about `<em>` only apply where cloze
    is on the table and the source carries markup — that is, not to transcripts.
    """
    if not property_depth:
        return ""
    rules = """
- **A property card needs a contrast or a condition.** The sentence has to separate \
this from that, or say when something holds. A sentence that merely states an idea, \
however important, holds no property card — stating ideas is what the cards above are \
for
- **Drop anything you could not grade.** If a reader could answer defensibly in several \
ways and the sentence does not force one of them, there is no card. A name has one \
right answer; a property only sometimes does, and the ones that do not are worse than \
nothing

  Passes: "You need backward compatibility only on {{c1::requests}}, and forward \
compatibility on responses." (the contrast forces exactly one answer)
  Fails:  "You can think of storing something in the database as {{c1::sending a \
message to your future self}}." (a metaphor has no single right wording — a reader who \
understands the point perfectly still cannot reproduce that phrase, so the card marks \
them wrong for knowing it)"""
    if not quote_source:
        return rules
    return rules + """
- **Hide a phrase, not a clause.** The deletion is a noun phrase or a qualifier: a few \
words. If you find yourself deleting half a sentence, there is no card here — that is \
transcription, not recall
- **Author emphasis is a hint, not a licence.** Where the source marks a phrase with \
<em> or <strong> — books use italic and bold for the same job — that is often exactly \
the span a property card should hide, and it is the best clue available. But the same \
markup also marks a term at its first use, a merely stressed word, and placeholders \
inside code — and most emphasised phrases earn no card at all"""


_CODE_INDICATORS = re.compile(
    r"(?:"
    r"(?:^|\n)\s*(?:def |class |import |from .+ import |public |private |protected |void |int |return )"
    r"|(?:^|\n)\s*(?:if\s*\(|for\s*\(|while\s*\(|switch\s*\()"
    r"|\b(?:nullptr|NULL|this->|self\.|\.getInstance|@Override|@Test)"
    r"|\b(?:function\s+\w+\s*\(|const\s+\w+\s*=|=>\s*\{)"
    r"|(?:^|\n)\s*(?:#include|#define|#ifdef)"
    r"|(?:\{\s*\n.*\n\s*\})"
    r")",
    re.MULTILINE,
)


def detect_programming(text: str) -> bool:
    """Heuristic: is this text from a programming book?"""
    sample = text[:30000]
    hits = len(_CODE_INDICATORS.findall(sample))
    return hits >= 5


def _format_figures_section(
    captions: list[tuple[str, str]] | None,
) -> str:
    """Format book figures as a numbered list for the prompt."""
    if not captions:
        return ""
    lines = ["Available figures from the book (reference by ID in the image field):"]
    for img_id, caption in captions:
        lines.append(f"  [{img_id.upper()}] {caption}")
    return "\n".join(lines) + "\n\n"


def build_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    language: str,
    is_article: bool = False,
    is_programming: bool = False,
    book_image_captions: list[tuple[str, str]] | None = None,
    topic: str = "",
    is_transcript: bool = False,
) -> str:
    depth_instruction = DEPTH_INSTRUCTIONS[depth]

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Generate cards ONLY about: {topic}. "
            "Skip everything unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    if is_article:
        source_header = f'Article: "{book_title}"'
        context_rule = (
            "- **Make questions self-contained**: cards are reviewed mixed with other decks, "
            "so include enough topic context in each question that the reader knows what domain "
            "it belongs to. Never say \"the article\", \"the author\", \"this section\" — "
            "use specific names, concepts, or topic references instead"
        )
        text_label = "Article text"
    else:
        source_header = f'Book: "{book_title}"\nChapter: "{chapter_title}"'
        context_rule = (
            "- **Make questions self-contained**: never say \"the chapter\", \"the author\", "
            "\"this section\" — use specific names, concepts, or book title instead. "
            "Cards are reviewed out of context"
        )
        text_label = "Chapter text"

    example_rule = (
        '\n- **Example field**: make cards usable as standalone learning material, not just memory prompts. '
        'For every non-trivial concept, fill the "example" field with a concrete example, scenario, '
        "counterexample, common gotcha, misconception, vivid analogy, or connection to another concept. "
        "Draw from both the book's own examples and your broader knowledge when that helps clarify the idea. "
        'Leave "example" as an empty string only for atomic facts where an example would add no value'
    )

    programming_rules = ""
    if is_programming:
        programming_rules = """
- **Focus on "why" and "when"**: prefer cards like "When would you use X?" or "What problem does X solve?" over "What is the syntax for X?"
- **Technique cards**: for named techniques/patterns/refactorings, test: (1) what problem it solves, (2) how it works, (3) when to apply it
- **Trade-off cards**: when the text compares approaches, create cards that test understanding of trade-offs
- **No trivial syntax cards**: don't create cards for basic language syntax that any developer would know"""
        example_rule = (
            '\n- **Example field**: make cards usable as standalone learning material, not just memory prompts. '
            'For every non-trivial programming concept, idiom, API, pattern, or concurrency rule, fill the '
            '"example" field with a minimal code snippet, concrete scenario, counterexample, common gotcha, '
            "real-world failure mode, or connection to related concepts. Use <pre><code>...</code></pre> "
            "for code snippets. Draw from both the book's own examples and your broader knowledge when that "
            'helps clarify the idea. Leave "example" as an empty string only for atomic facts where an example '
            "would add no value"
        )

    has_book_images = bool(book_image_captions)

    image_rule = ""
    if has_book_images:
        image_rule = (
            '\n- **Image field**: include an optional "image" field. '
            "If one of the available book figures matches the card's concept, "
            f"reference it by writing its ID followed by a short caption in {language} "
            "(e.g. \"[BOOK-IMG-1] short description of the figure\"). "
            f"The caption after the ID is REQUIRED and must be in {language}. "
            "Prefer using book figures when they help understand the concept visually. "
            'Leave "image" as empty string when not needed'
        )

    code_format_note = ""
    if is_programming:
        code_format_note = (
            "\n\nIMPORTANT: All fields are rendered as HTML. For code snippets use "
            "<pre><code>...</code></pre> tags."
        )

    redundancy_rule = ""
    if depth >= 2:
        redundancy_rule = (
            "\n- **Test key concepts from multiple angles**: for important ideas, "
            "add both a definition card and an application card"
        )

    term_section = _term_cards_section(
        depth, language, quote_source=not is_transcript,
    )

    return f"""You are an expert at creating Anki flashcards from {"articles" if is_article else "books"}.

{source_header}
Language: {language}

{depth_instruction}{topic_instruction}

Guidelines:
- **Minimum information principle**: one idea per card. Prefer splitting long lists into separate cards over bundling them into one answer
- **Mix question types**: factual recall, conceptual understanding, and application
- **Write cards in {language}**
- **No trivial cards**: every card should test something genuinely worth remembering
- **No meta-cards**: never create cards about the book's structure, what a chapter covers, the author's approach, or how the book is organized. Only test the actual subject matter — the ideas, facts, and concepts themselves. If a chapter is mostly introductory or structural with little substantive content, generate fewer cards
{context_rule}
- **Disambiguate confusable concepts**: highlight the distinguishing feature when similar terms or processes appear
- **Add a domain label**: if a term is ambiguous across fields, prefix the question — e.g. "(genetics) What is GRE?"
- **Build on fundamentals**: include prerequisite concepts in the question rather than assuming prior cards
- **Logical order**: arrange cards so foundational concepts come first — definitions before applications, causes before effects
- **Answers should be concise but complete** — typically 1-3 sentences
- **Lists in answers**: when an answer contains a numbered or bulleted list, use <br> between items for readability
- **No italic or emphasis markup**: do not use <em>, <i>, or any italic formatting. Where the source text below carries <em> or <strong>, that is the author's own emphasis, preserved so you can see which words they stressed — it is information for you, not markup to copy. Leave the tags out of every card you write{programming_rules}{redundancy_rule}{example_rule}{image_rule}
{term_section}

{_format_figures_section(book_image_captions)}Output ONLY a JSON array of objects with "question", "answer", and optionally "example", "type" and "context"{' and "image"' if has_book_images else ''} fields. Both kinds of card go in the SAME array; where a term card happens to relate to one of the cards above, place it directly after that card. No markdown, no explanation, no wrapper — just the raw JSON array.{code_format_note}

Example format:
[
  {{"question": "What is X?", "answer": "X is...", "example": ""{', "image": ""' if has_book_images else ''}}},
  {{"question": "Why does Y happen?", "answer": "Because...", "example": "For instance, when Z occurs..."{', "image": "[BOOK-IMG-1] Description of the figure"' if has_book_images else ''}}},
  {{"type": "cloze", "question": "A sentence from the text in which the defined term is replaced by {{{{c1::the term}}}}.", "answer": "One-line gloss in {language}.", "context": "short orienting phrase"}},
  {{"type": "term", "question": "What is the term for <description of the concept>?", "answer": "The term"}}
]

{text_label}:
---
{chapter_text}
---

Generate the flashcards now as a JSON array:"""


def build_prompt_request(
    request: str,
    depth: int,
    language: str,
) -> str:
    """Build a prompt for source-free study material generated from model knowledge."""
    depth_instruction = DEPTH_INSTRUCTIONS[depth]

    return f"""You are an expert teacher creating standalone Anki flashcards from a study request.

Study request:
---
{request}
---

Language: {language}

{depth_instruction}

Guidelines:
- **Use your broader knowledge** to teach the requested topic accurately and practically
- **Deck title**: create a concise, human-readable title for the deck, normally 3-7 words. Prefer the topic and practical angle over copying the full request
- **Minimum information principle**: one idea per card. Prefer splitting long lists into separate cards over bundling them into one answer
- **Make every card self-contained**: include enough topic context in each question that the card can be reviewed on its own
- **Mix question types**: factual recall, conceptual understanding, application, diagnosis, and trade-offs
- **Write cards in {language}**
- **No trivial cards**: every card should test something genuinely worth remembering
- **No meta-cards**: never create cards about the request itself, your approach, or the generated deck structure
- **Disambiguate confusable concepts**: highlight the distinguishing feature when similar terms or processes appear
- **Build on fundamentals**: include prerequisite concepts in the question rather than assuming prior cards
- **Logical order**: arrange cards so foundational concepts come first — definitions before applications, causes before effects
- **Answers should be concise but complete** — typically 1-3 sentences
- **Lists in answers**: when an answer contains a numbered or bulleted list, use <br> between items for readability
- **No italic or emphasis markup**: do not use <em>, <i>, or any italic formatting
- **Example field**: make cards usable as standalone learning material, not just memory prompts. For every non-trivial concept, fill the "example" field with a concrete example, scenario, counterexample, common gotcha, misconception, vivid analogy, or practical application. If the request involves software engineering or programming, include code snippets where they clarify the idea and use <pre><code>...</code></pre> tags. Leave "example" as an empty string only for atomic facts where an example would add no value

Output ONLY a JSON object with "title" and "cards" fields. The "title" field is a concise deck title. The "cards" field is an array of objects with "question", "answer", and optionally "example" fields. No markdown, no explanation, no wrapper — just the raw JSON object.

Example format:
{{
  "title": "Cognitive Load for Engineers",
  "cards": [
    {{"question": "What is X?", "answer": "X is...", "example": ""}},
    {{"question": "How would you apply Y in practice?", "answer": "Use Y when...", "example": "For example, in a software team..."}}
  ]
}}

Generate the deck now as a JSON object:"""


VALID_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


_LANG_NAMES: dict[str, str] = {
    "en": "English", "ru": "Russian", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "no": "Norwegian", "nb": "Norwegian",
    "sv": "Swedish", "da": "Danish", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "ar": "Arabic", "he": "Hebrew", "uk": "Ukrainian",
    "cs": "Czech", "fi": "Finnish",
}


def build_vocab_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    level: str,
    native_language: str,
    is_article: bool = False,
    topic: str = "",
) -> str:
    """Build a prompt to extract vocabulary above the reader's level."""
    native_name = _LANG_NAMES.get(native_language, native_language)
    if is_article:
        source_header = f'Article: "{book_title}"'
        text_label = "Article text"
    else:
        source_header = f'Book: "{book_title}"\nChapter: "{chapter_title}"'
        text_label = "Chapter text"

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Extract vocabulary ONLY related to: {topic}. "
            "Skip words unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    return f"""You are an expert language teacher creating Anki vocabulary cards.

{source_header}
Reader's level: {level} (CEFR)
Reader's native language: {native_name}
Translate to: {native_name}

Extract words and phrases from the text that a {level}-level reader would NOT already know. \
These are words above {level} — uncommon, literary, domain-specific, or idiomatic expressions \
that a learner at this level would benefit from studying.{topic_instruction}

Guidelines:
- **Skip common words** that any {level} reader would know
- **Include**: uncommon single words, idiomatic phrases, phrasal verbs, collocations, literary/formal vocabulary
- **Context sentence**: use the EXACT sentence from the text where the word appears (or shorten it if too long, but keep the word in context). Wrap the target word/phrase in **&lt;b&gt;** tags to highlight it
- **Translation**: natural translation to {native_name}, not word-for-word
- **Definition**: brief explanation in the source language (1 sentence max)
- **Example**: one additional example sentence (NOT from the text) showing typical usage. Wrap the target word/phrase in **&lt;b&gt;** tags
- **Pronunciation**: IPA transcription (e.g. "/juːˈbɪkwɪtəs/") — skip for phrases and idioms
- **Etymology**: brief word origin in the source language, starting with a label in that language (e.g. "Origin: Latin ubique = everywhere" for English, "Herkunft: Latein ubique = überall" for German). Skip for common roots or phrases
- **Dictionary form**: ALWAYS use the base/dictionary form in the "word" field, even if the text has an inflected form. Verbs must be infinitive with "to" (e.g. text says "ensconced" → word is "to ensconce"; text says "crouching" → word is "to crouch"). Nouns must be singular. Adjectives must be positive degree
- **Correct spelling**: spell the word using standard, correct dictionary spelling. It must be the same word that appears highlighted in the context sentence (just its base form) — never invent, misspell, or guess a word that is not actually in the text
- **Grammar notes**: when useful, add brief grammar info in the "word" field that the READER can understand — e.g. gender for nouns (der/die/das, le/la). Use notation the reader knows based on their native language. Skip for English and Russian words
- **No proper nouns** (names of people, places, brands) unless they have a general meaning
- **No numbers, dates, or abbreviations**
- For phrases/idioms: the "word" field should contain the full phrase in base form

Output ONLY a JSON array. No markdown, no explanation, no wrapper.

Example format:
[
  {{"word": "ubiquitous", "pronunciation": "/juːˈbɪkwɪtəs/", "context": "Smartphones have become <b>ubiquitous</b> in modern life.", "translation": "...", "definition": "Present or found everywhere", "example": "Coffee shops are <b>ubiquitous</b> in big cities.", "etymology": "Latin ubique = everywhere"}},
  {{"word": "to come to grips with", "pronunciation": "", "context": "She had to <b>come to grips with</b> the new reality.", "translation": "...", "definition": "To begin to understand and deal with something difficult", "example": "It took him months to <b>come to grips with</b> the loss.", "etymology": ""}}
]

{text_label}:
---
{chapter_text}
---

Extract vocabulary above {level} as a JSON array:"""


PRACTICE_DEPTH_INSTRUCTIONS = {
    0: (
        "Identify only the single most important pattern or technique "
        "worth practicing from this chapter. Generate exercise cards for it only."
    ),
    1: (
        "Identify the core patterns, techniques, or implementations from this chapter "
        "that are worth practicing. Skip minor utilities and trivial examples."
    ),
    2: (
        "Identify all important patterns, techniques, and implementations from this "
        "chapter, including secondary patterns and notable edge cases."
    ),
    3: (
        "Identify every pattern, technique, implementation, and idiom from this chapter "
        "that could appear in production code or interviews. Be comprehensive."
    ),
}


def build_practice_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    topic: str = "",
    code_lang: str = "",
) -> str:
    """Build a prompt to generate programming practice exercise cards."""
    depth_instruction = PRACTICE_DEPTH_INSTRUCTIONS[depth]

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Generate exercises ONLY related to: {topic}. "
            "Skip everything unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    code_lang_instruction = ""
    if code_lang:
        code_lang_instruction = (
            f"\n\nIMPORTANT: ALL code in questions and answers MUST be in {code_lang}. "
            f"Even if the book uses a different language, translate all examples to {code_lang}."
        )

    return f"""You are an expert programming instructor creating Anki exercise cards \
from a programming book.

Book: "{book_title}"
Chapter: "{chapter_title}"

{depth_instruction}{topic_instruction}{code_lang_instruction}

For each pattern or technique you identify, generate an "Implement ..." exercise card:
- **Question**: a concrete specification formatted as readable HTML for Anki. \
Structure the question with: a short bold title, a plain-language goal, a separate \
API block for signatures, and requirements/edge cases as HTML lists. Avoid mixing \
normal prose and inline <code> heavily in the same sentence; use inline <code> only \
for rare single identifiers. Put class/method signatures in a dedicated \
<pre><code>...</code></pre> block. Example:

<b>Implement a thread-safe LRU cache</b><br><br>\
Goal:<br>\
Build a cache that keeps recently used entries available and evicts older entries \
when capacity is reached.<br><br>\
API:<br>\
<pre><code>class LRUCache&lt;K, V&gt;
V get(K key)
void put(K key, V value)</code></pre>\
Requirements:\
<ul>\
  <li>Use a fixed positive capacity.</li>\
  <li>Reading a value marks it as recently used.</li>\
  <li>Adding beyond capacity evicts the least recently used entry.</li>\
  <li>Missing keys return null.</li>\
  <li>Implementation must be thread-safe.</li>\
</ul>\
Edge cases:\
<ul>\
  <li>Updating an existing key must not increase size.</li>\
  <li>Zero or negative capacity should be rejected.</li>\
</ul>

- **Answer**: complete, compilable, production-quality code — not pseudocode. \
Include brief inline comments only where a non-obvious design decision is made

Guidelines:
- **Skip purely non-technical chapters**: only return an empty JSON array [] for \
chapters that have NO technical content at all (e.g. preface, acknowledgments). \
Chapters about system design, architecture, or algorithms are valid — even if the \
book discusses them without code, create exercises that implement the key components \
(e.g. a chapter about rate limiting → implement a sliding window rate limiter; \
a chapter about URL shortening → implement the shortening service with Base62 encoding)
- **Answers with code must use <pre><code> tags**
- **One exercise per distinct pattern**: don't generate multiple exercises for the \
same pattern unless they test meaningfully different aspects
- **Specifications must be precise**: include class/method names, parameter types, \
return types, thread-safety requirements, and any constraints the solution must satisfy
- **Question names define the production API**: class names, method names, and \
signatures in the question must describe the thing being implemented, independent \
of any runnable demo. Do not add names like Demo, Example, Runner, App, or Test \
only because the answer includes a main method. Do not mention the main method in \
the question unless the actual exercise is to build a CLI or application entry point
- **Solutions must be self-contained**: a reader should be able to type the answer \
into an IDE and have it compile
- **Runnable demonstrations**: when the target language supports it, include a \
runnable demonstration entry point in the answer alongside the implementation where practical. \
For Java, prefer a complete single-file Java 17+ example with \
`public static void main(String[] args)` inside the primary implementation class \
or another naturally named class that is already part of the solution. The main \
method is only a learning/debugging harness: it must not change the required API, \
class names, or question wording. Use it to exercise the implementation, show \
expected behavior, and cover at least one important edge case. For concurrency \
exercises, demonstrate realistic multi-threaded usage with APIs such as \
ExecutorService, CountDownLatch, CompletableFuture, or locks where appropriate. \
Omit the entry point only when it would make the solution misleading or distract \
from the concept
- **Production-ready code**: solutions must use proper concurrency primitives \
(e.g. ConcurrentHashMap, ReadWriteLock, not blanket synchronized), correct error \
handling, and idiomatic patterns — the kind of code you'd put in a real codebase, \
not textbook simplifications. Use explicit type annotations and modern language \
idioms. Examples (not exhaustive): Python 3.10+ — `X | None` not `Optional[X]`, \
`list[int]` not `List[int]`, `@dataclass` for data carriers (DTOs, configs, value \
objects), never use `Any`; \
Java 17+ — records, sealed interfaces, `var`, `List.of()`, pattern matching in switch

Output ONLY a JSON array. No markdown, no explanation, no wrapper.

[
  {{"question": "<b>Implement a Builder for NutritionFacts</b><br><br>\
Goal:<br>Create an immutable value object using the Builder pattern.<br><br>\
API:<br><pre><code>class NutritionFacts\\nNutritionFacts.Builder(int servingSize)\
\\nBuilder calories(int value)\\nBuilder fat(int value)\\nBuilder sodium(int value)\
\\nNutritionFacts build()</code></pre>\
Requirements:<ul><li>Require serving size when the builder is created.</li>\
<li>Default calories, fat, and sodium to zero.</li>\
<li>Keep the built object immutable: final fields and no setters.</li>\
<li>Validate that serving size is positive before creating the object.</li></ul>", \
"answer": "<pre><code>public class NutritionFacts {{\\n    private final int servingSize;\
\\n    private final int calories;\\n    private final int fat;\\n    private final int sodium;\
\\n\\n    private NutritionFacts(Builder builder) {{\\n        this.servingSize = builder.servingSize;\
\\n        this.calories = builder.calories;\\n        this.fat = builder.fat;\\n        this.sodium = builder.sodium;\
\\n    }}\\n\\n    public static class Builder {{\\n        private final int servingSize;\
\\n        private int calories;\\n        private int fat;\\n        private int sodium;\
\\n\\n        public Builder(int servingSize) {{\\n            this.servingSize = servingSize;\
\\n        }}\\n\\n        public Builder calories(int val) {{ calories = val; return this; }}\
\\n        public Builder fat(int val) {{ fat = val; return this; }}\\n        public Builder sodium(int val) {{ sodium = val; return this; }}\
\\n\\n        public NutritionFacts build() {{\\n            if (servingSize <= 0) throw new IllegalArgumentException(\\\"servingSize must be positive\\\");\
\\n            return new NutritionFacts(this);\\n        }}\\n    }}\\n\\n    @Override\
\\n    public String toString() {{\\n        return \\\"NutritionFacts[servingSize=\\\" + servingSize + \\\", calories=\\\" + calories + \\\", fat=\\\" + fat + \\\", sodium=\\\" + sodium + \\\"]\\\";\
\\n    }}\\n\\n    public static void main(String[] args) {{\\n        NutritionFacts facts = new NutritionFacts.Builder(240).calories(100).sodium(35).build();\
\\n        System.out.println(facts);\\n\\n        try {{\\n            new NutritionFacts.Builder(0).build();\
\\n        }} catch (IllegalArgumentException expected) {{\\n            System.out.println(expected.getMessage());\
\\n        }}\\n    }}\\n}}</code></pre>", \
"example": ""}}
]

Chapter text:
---
{chapter_text}
---

Generate the exercise cards now as a JSON array:"""
