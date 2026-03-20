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


def build_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    language: str,
    is_article: bool = False,
    is_programming: bool = False,
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

    programming_rules = ""
    if is_programming:
        programming_rules = """
- **Code in answers**: when a concept is best illustrated with code, include a short snippet (3-6 lines max) using <pre><code> tags. Only include code when it genuinely helps — not every card needs it
- **Focus on "why" and "when"**: prefer cards like "When would you use X?" or "What problem does X solve?" over "What is the syntax for X?"
- **Technique cards**: for named techniques/patterns/refactorings, test: (1) what problem it solves, (2) how it works, (3) when to apply it
- **Trade-off cards**: when the text compares approaches, create cards that test understanding of trade-offs
- **No trivial syntax cards**: don't create cards for basic language syntax that any developer would know"""

    code_format_note = ""
    if is_programming:
        code_format_note = (
            "\n\nIMPORTANT: Answers are rendered as HTML. For code snippets use "
            "<pre><code>...</code></pre> tags."
        )

    return f"""You are an expert at creating Anki flashcards from nonfiction {"articles" if is_article else "books"}.

{source_header}
Language: {language}

{depth_instruction}

Guidelines:
- **Minimum information principle**: one idea per card
- **Mix question types**: factual recall, conceptual understanding, and application
- **Write cards in the same language as the {"article" if is_article else "book"}** ({language})
- **No trivial cards**: every card should test something genuinely worth remembering
- **No cards about page numbers, chapter structure, or meta-information**
{context_rule}
- **Answers should be concise but complete** — typically 1-3 sentences{programming_rules}

Output ONLY a JSON array of objects with "question" and "answer" fields. No markdown, no explanation, no wrapper — just the raw JSON array.{code_format_note}

Example format:
[
  {{"question": "What is X?", "answer": "X is..."}},
  {{"question": "Why does Y happen?", "answer": "Because..."}}
]

{text_label}:
---
{chapter_text}
---

Generate the flashcards now as a JSON array:"""
