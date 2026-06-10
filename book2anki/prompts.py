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
        '\n- **Example field**: include an optional "example" field — prefer vivid, surprising, '
        "or counterintuitive illustrations over generic ones. Can go beyond the book's own examples. "
        'Leave "example" as empty string when not needed'
    )

    programming_rules = ""
    if is_programming:
        programming_rules = """
- **Focus on "why" and "when"**: prefer cards like "When would you use X?" or "What problem does X solve?" over "What is the syntax for X?"
- **Technique cards**: for named techniques/patterns/refactorings, test: (1) what problem it solves, (2) how it works, (3) when to apply it
- **Trade-off cards**: when the text compares approaches, create cards that test understanding of trade-offs
- **No trivial syntax cards**: don't create cards for basic language syntax that any developer would know"""
        example_rule = (
            '\n- **Example field**: include an optional "example" field with illustrative code snippets. '
            "Prefer striking before/after contrasts or surprising edge cases. "
            "Use <pre><code> tags for code. "
            'Leave "example" as empty string when not needed'
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
- **No italic or emphasis markup**: do not use <em>, <i>, or any italic formatting{programming_rules}{redundancy_rule}{example_rule}{image_rule}

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
- **Question**: a concrete specification — what to implement, required behavior, \
constraints, and edge cases. Go BEYOND the book's own examples — use your knowledge \
to create realistic, interview-quality exercises that apply the chapter's patterns \
(e.g. implement an LRU cache, a thread-safe singleton, a retry-with-backoff utility). \
The best exercises are ones a developer would actually need in production
- **Answer**: complete, compilable, production-quality code — not pseudocode. \
Include brief inline comments only where a non-obvious design decision is made

Guidelines:
- **Skip non-practical chapters**: if the chapter has no implementable code patterns, \
return an empty JSON array []
- **Answers with code must use <pre><code> tags**
- **One exercise per distinct pattern**: don't generate multiple exercises for the \
same pattern unless they test meaningfully different aspects
- **Specifications must be precise**: include class/method names, parameter types, \
return types, thread-safety requirements, and any constraints the solution must satisfy
- **Solutions must be self-contained**: a reader should be able to type the answer \
into an IDE and have it compile
- **Production-ready code**: solutions must use proper concurrency primitives \
(e.g. ConcurrentHashMap, ReadWriteLock, not blanket synchronized), correct error \
handling, and idiomatic patterns — the kind of code you'd put in a real codebase, \
not textbook simplifications

Output ONLY a JSON array. No markdown, no explanation, no wrapper.

[
  {{"question": "Implement a Builder for NutritionFacts with required servingSize \
(int) and optional calories, fat, sodium (all int, default 0). The built object \
must be immutable. Validate that servingSize > 0 in build().", \
"answer": "<pre><code>public class NutritionFacts {{\\n    private final int servingSize;\
\\n    private final int calories;\\n    private final int fat;\\n    private final int \
sodium;\\n\\n    private NutritionFacts(Builder builder) {{\\n        this.servingSize = \
builder.servingSize;\\n        this.calories = builder.calories;\\n        this.fat = \
builder.fat;\\n        this.sodium = builder.sodium;\\n    }}\\n\\n    public static \
class Builder {{\\n        private final int servingSize;\\n        private int calories;\
\\n        private int fat;\\n        private int sodium;\\n\\n        public Builder\
(int servingSize) {{\\n            this.servingSize = servingSize;\\n        }}\\n\\n\
        public Builder calories(int val) {{ calories = val; return this; }}\\n        \
public Builder fat(int val) {{ fat = val; return this; }}\\n        public Builder \
sodium(int val) {{ sodium = val; return this; }}\\n\\n        public NutritionFacts \
build() {{\\n            if (servingSize <= 0) throw new IllegalArgumentException();\
\\n            return new NutritionFacts(this);\\n        }}\\n    }}\\n}}</code></pre>", \
"example": ""}}
]

Chapter text:
---
{chapter_text}
---

Generate the exercise cards now as a JSON array:"""
