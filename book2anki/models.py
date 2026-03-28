import re
from dataclasses import dataclass, field


@dataclass
class BookImage:
    """An image extracted from the source book or web page."""
    id: str          # "book-img-1" (per-chapter sequential)
    data: bytes      # raw image bytes (empty if url is set)
    ext: str         # file extension: "png", "jpg", etc.
    caption: str     # description for the LLM
    url: str = ""    # source URL for lazy download (web images)


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
    "also by", "title page", "titlepage", "about the author", "about the authors",
    "about the publisher", "about this ebook",
    "acknowledgments", "acknowledgements", "bibliography", "notes", "index",
    "credits", "cover", "illustrations", "glossary", "preface", "foreword",
    "appendix", "endnotes", "praise", "annotation", "maps",
    "works by", "other books by",
    "содержание", "оглавление", "предисловие", "вступление",
    "об авторе", "об авторах", "благодарности", "библиография", "словарик",
    "посвящение", "примечания", "алфавитный указатель",
    "приложение", "сноски", "комментарии", "иллюстрации",
    "список литературы", "дисклеймер", "карты",
    "источники иллюстраций", "аннотация", "от автора",
}

MIN_CHAPTER_LENGTH = 500  # chars — skip trivially short pages (title pages, separators)

_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)

_NUMBERED_TITLE_RE = None


def _is_numbered_title(title: str) -> bool:
    """Return True if title looks like a numbered chapter (Глава I, Chapter 3, etc.)."""
    global _NUMBERED_TITLE_RE
    if _NUMBERED_TITLE_RE is None:
        _NUMBERED_TITLE_RE = re.compile(
            r"(?:^|\s—\s)"  # start or "Section — " prefix
            r"(\d+[\.\s:]|chapter\s|глава\s|раздел\s|лекция\s|книга\s|book\s)",
            re.IGNORECASE,
        )
    return bool(_NUMBERED_TITLE_RE.search(title.strip()))


def _is_skip_match(title_lower: str, skip: str) -> bool:
    """Check if a skip title matches as a whole word in the title."""
    return bool(re.search(r'\b' + re.escape(skip) + r'\b', title_lower))


def should_skip_chapter(title: str, text: str, book_title: str = "") -> bool:
    """Skip non-content sections like copyright, bibliography, etc."""
    title_lower = title.lower().strip()
    if any(_is_skip_match(title_lower, skip) for skip in SKIP_TITLES):
        return True
    if title_lower.startswith("section "):
        return True
    if title_lower.isdigit():
        return True
    if len(title_lower) <= 2 and not _ROMAN_RE.match(title_lower):
        return True
    if len(text) < MIN_CHAPTER_LENGTH and not _is_numbered_title(title):
        return True
    if book_title and title.strip().lower() == book_title.strip().lower():
        # Only skip short title-page entries, not real content chapters
        if len(text) < MIN_CHAPTER_LENGTH:
            return True
    return False
