from dataclasses import dataclass, field


@dataclass
class BookImage:
    """An image extracted from the source book."""
    id: str          # "book-img-1" (per-chapter sequential)
    data: bytes      # raw image bytes
    ext: str         # file extension: "png", "jpg", etc.
    caption: str     # description for the LLM


@dataclass
class Chapter:
    title: str
    text: str
    index: int
    images: list[BookImage] = field(default_factory=list)


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __iadd__(self, other: "TokenUsage") -> "TokenUsage":
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        return self


@dataclass
class Card:
    question: str
    answer: str
    chapter_title: str
    book_title: str
    source_url: str = ""
    example: str = ""
    image: str = ""


SKIP_TITLES = {
    "copyright", "dedication", "epigraph", "contents", "table of contents",
    "also by", "title page", "about the author", "about the authors",
    "acknowledgments", "acknowledgements", "bibliography", "notes", "index",
    "credits", "cover", "illustrations", "glossary", "preface", "foreword",
    "introduction",
    "prologue", "epilogue", "appendix",
    "содержание", "оглавление", "предисловие", "вступление", "введение",
    "об авторе", "об авторах", "благодарности", "библиография", "словарик",
    "посвящение", "примечания", "алфавитный указатель",
    "пролог", "эпилог", "приложение",
}

MIN_CHAPTER_LENGTH = 3000  # chars — skip very short sections


def should_skip_chapter(title: str, text: str, book_title: str = "") -> bool:
    """Skip non-content sections like copyright, bibliography, etc."""
    title_lower = title.lower().strip()
    if any(skip in title_lower for skip in SKIP_TITLES):
        return True
    if title_lower.startswith("section "):
        return True
    if len(text) < MIN_CHAPTER_LENGTH:
        return True
    if book_title and book_title.strip() in title.strip():
        return True
    return False
