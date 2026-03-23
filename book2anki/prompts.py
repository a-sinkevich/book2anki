import re

DEPTH_INSTRUCTIONS = {
    0: (
        "Generate only 2-3 cards capturing the single most important ideas — "
        "the main thesis and one or two key facts worth remembering long-term. "
        "Nothing else. This is a minimal summary, not a study guide."
    ),
    1: (
        "Generate cards that test understanding of the chapter's core ideas: "
        "the main thesis, key arguments, and central takeaways. "
        "Skip supporting details, examples, and nuances — focus only on what's essential."
    ),
    2: (
        "Generate cards that test understanding of core ideas plus important supporting material: "
        "key evidence, notable examples, important distinctions, and secondary arguments. "
        "Skip minor details and tangential asides."
    ),
    3: (
        "Generate cards that test thorough understanding of the chapter: "
        "core ideas, supporting evidence, specific data points, case studies, "
        "named frameworks, important quotes, and all significant details."
    ),
}

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
        '\n- **Example field**: include an optional "example" field with a concrete illustration '
        "when it helps understand the concept — a real-world scenario, a classic case, "
        "an analogy, or a brief demonstration. Can go beyond the book's own examples. "
        'Leave "example" as empty string when not needed — not every card needs one'
    )

    programming_rules = ""
    if is_programming:
        programming_rules = """
- **Focus on "why" and "when"**: prefer cards like "When would you use X?" or "What problem does X solve?" over "What is the syntax for X?"
- **Technique cards**: for named techniques/patterns/refactorings, test: (1) what problem it solves, (2) how it works, (3) when to apply it
- **Trade-off cards**: when the text compares approaches, create cards that test understanding of trade-offs
- **No trivial syntax cards**: don't create cards for basic language syntax that any developer would know"""
        example_rule = (
            '\n- **Example field**: include an optional "example" field with an illustrative code snippet '
            "when it helps understand the concept. Use <pre><code> tags for code. "
            "Can go beyond the book's own examples. "
            'Leave "example" as empty string when not needed — not every card needs one. '
            "Good candidates: patterns, techniques, refactorings, before/after transformations"
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

    return f"""You are an expert at creating Anki flashcards from {"articles" if is_article else "books"}.

{source_header}
Language: {language}

{depth_instruction}{topic_instruction}

Guidelines:
- **Minimum information principle**: one idea per card
- **Mix question types**: factual recall, conceptual understanding, and application
- **Write cards in {language}**
- **No trivial cards**: every card should test something genuinely worth remembering
- **No cards about page numbers, chapter structure, or meta-information**
{context_rule}
- **Answers should be concise but complete** — typically 1-3 sentences
- **Lists in answers**: when an answer contains a numbered or bulleted list, use <br> between items for readability
- **No italic or emphasis markup**: do not use <em>, <i>, or any italic formatting{programming_rules}{example_rule}{image_rule}

{_format_figures_section(book_image_captions)}Output ONLY a JSON array of objects with "question", "answer", and optionally "example"{' and "image"' if has_book_images else ''} fields. No markdown, no explanation, no wrapper — just the raw JSON array.{code_format_note}

Example format:
[
  {{"question": "What is X?", "answer": "X is...", "example": ""{', "image": ""' if has_book_images else ''}}},
  {{"question": "Why does Y happen?", "answer": "Because...", "example": "For instance, when Z occurs..."{', "image": "[BOOK-IMG-1] Description of the figure"' if has_book_images else ''}}}
]

{text_label}:
---
{chapter_text}
---

Generate the flashcards now as a JSON array:"""


VALID_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


def build_vocab_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    level: str,
    native_language: str,
    is_article: bool = False,
) -> str:
    """Build a prompt to extract vocabulary above the reader's level."""
    if is_article:
        source_header = f'Article: "{book_title}"'
        text_label = "Article text"
    else:
        source_header = f'Book: "{book_title}"\nChapter: "{chapter_title}"'
        text_label = "Chapter text"

    return f"""You are an expert language teacher creating Anki vocabulary cards.

{source_header}
Reader's level: {level} (CEFR)
Translate to: {native_language}

Extract words and phrases from the text that a {level}-level reader would NOT already know. \
These are words above {level} — uncommon, literary, domain-specific, or idiomatic expressions \
that a learner at this level would benefit from studying.

Guidelines:
- **Skip common words** that any {level} reader would know
- **Include**: uncommon single words, idiomatic phrases, phrasal verbs, collocations, literary/formal vocabulary
- **Context sentence**: use the EXACT sentence from the text where the word appears (or shorten it if too long, but keep the word in context)
- **Translation**: natural translation to {native_language}, not word-for-word
- **Definition**: brief explanation in the source language (1 sentence max)
- **Example**: one additional example sentence (NOT from the text) showing typical usage
- **Dictionary form**: always use the base/dictionary form in the "word" field (infinitive for verbs, singular for nouns, etc.), even if the text has an inflected form
- **No proper nouns** (names of people, places, brands) unless they have a general meaning
- **No numbers, dates, or abbreviations**
- For phrases/idioms: the "word" field should contain the full phrase in base form

Output ONLY a JSON array. No markdown, no explanation, no wrapper.

Example format:
[
  {{"word": "ubiquitous", "context": "Smartphones have become ubiquitous in modern life.", "translation": "...", "definition": "Present or found everywhere", "example": "Coffee shops are ubiquitous in big cities."}},
  {{"word": "to come to grips with", "context": "She had to come to grips with the new reality.", "translation": "...", "definition": "To begin to understand and deal with something difficult", "example": "It took him months to come to grips with the loss."}}
]

{text_label}:
---
{chapter_text}
---

Extract vocabulary above {level} as a JSON array:"""
