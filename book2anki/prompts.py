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


def build_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    language: str,
    is_article: bool = False,
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
- **Answers should be concise but complete** — typically 1-3 sentences

Output ONLY a JSON array of objects with "question" and "answer" fields. No markdown, no explanation, no wrapper — just the raw JSON array.

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
