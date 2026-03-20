import re

DEPTH_INSTRUCTIONS = {
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
) -> str:
    depth_instruction = DEPTH_INSTRUCTIONS[depth]

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
            "reference it by writing its ID (e.g. [BOOK-IMG-1]). "
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

{depth_instruction}

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
  {{"question": "Why does Y happen?", "answer": "Because...", "example": "For instance, when Z occurs..."{', "image": "[BOOK-IMG-1]"' if has_book_images else ''}}}
]

{text_label}:
---
{chapter_text}
---

Generate the flashcards now as a JSON array:"""
