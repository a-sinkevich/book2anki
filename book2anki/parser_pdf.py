import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from book2anki.models import BookImage, Chapter, should_skip_chapter

_MIN_IMAGE_BYTES = 5000
_FIGURE_RE = re.compile(
    r"^(fig(ure|\.)|рис(унок|\.)|diagram|схема|table|таблица|chart|график)",
    re.IGNORECASE,
)

CHUNK_SIZE = 20  # pages per chunk in fallback mode

# Outline sections longer than this are split into their subsections
MAX_CHAPTER_CHARS = 30000
_FRONT_MATTER_MAX_CHARS = 5000  # cover/contents entry repeating the book title

_COVER_PAGES = 3  # pages scanned for a cover title
_COVER_TITLE_MAX_CHARS = 150

# "Chapter 1: ...", "Part 2", "3. ...", "5.1: ..." — a section heading, not a book title
_SECTION_TITLE_RE = re.compile(
    r"^(chapter|part|section|глава|раздел)\s+\d+"
    r"|^\d{1,2}(\.\d+)*\s*[.:]\s*\S",
    re.IGNORECASE,
)

CHAPTER_PATTERNS = [
    re.compile(r"^chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^part\s+\d+", re.IGNORECASE),
    re.compile(r"^(introduction|conclusion|epilogue|prologue|preface|afterword)", re.IGNORECASE),
    re.compile(r"^\d+\.\s+\w", re.IGNORECASE),  # "1. Title"
    re.compile(r"^[IVXLC]+\.\s+\w"),  # Roman numerals
]


def parse_pdf(filepath: str) -> tuple[str, list[Chapter]]:
    """Parse a PDF file and return (book_title, chapters)."""
    # Suppress MuPDF warnings about malformed PDF internals
    fitz.TOOLS.mupdf_display_errors(False)
    doc = fitz.open(filepath)

    if doc.is_encrypted:
        raise ValueError(f"PDF is password-protected: {filepath}")

    book_title = _extract_title(doc, filepath)

    sample_text = ""
    for page_num in range(min(5, len(doc))):
        sample_text += doc[page_num].get_text()
    if len(sample_text.strip()) < 50:
        raise ValueError(
            f"PDF appears to be scanned (no text layer): {filepath}. "
            "Consider using an OCR tool first."
        )

    chapters = _from_outline(doc, book_title)
    if not chapters:
        chapters = _from_heuristics(doc)
    if not chapters:
        chapters = _from_fixed_chunks(doc)
        print("\n⚠️  No chapter structure detected — splitting by page chunks."
              "\n    Try the EPUB version if available.\n")

    doc.close()
    return book_title, chapters


def _extract_title(doc: fitz.Document, filepath: str) -> str:
    metadata = doc.metadata
    title = (metadata.get("title") or "").strip() if metadata else ""
    if (
        title
        and not re.match(r"^[\d\-]+(\.\w+)?$", title)
        and "." not in title
        and not _SECTION_TITLE_RE.match(title)
    ):
        return title
    cover_title = _title_from_cover(doc)
    if cover_title:
        return cover_title
    return Path(filepath).stem.replace("-", " ").replace("_", " ").title()


def _title_from_cover(doc: fitz.Document) -> str:
    """Read the book title from the largest text on the opening pages."""
    try:
        parts = _largest_text_on_cover(doc)
    except Exception:
        return ""  # unusual or damaged PDF — let the caller fall back
    title = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(title) < 4 or len(title) > _COVER_TITLE_MAX_CHARS:
        return ""
    if not re.search(r"[^\W\d_]", title):  # no letters — page numbers, decoration
        return ""
    if _SECTION_TITLE_RE.match(title):  # first page is a chapter, not a cover
        return ""
    return title


def _largest_text_on_cover(doc: fitz.Document) -> list[str]:
    """Collect the text spans set in the biggest font size on the opening pages."""
    best_size = 0.0
    best_parts: list[str] = []

    for page_num in range(min(_COVER_PAGES, len(doc))):
        by_size: dict[float, list[str]] = {}
        for block in doc[page_num].get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = _collapse_spaced(span["text"].replace("\xad", "").strip())
                    if len(text) < 2 or len(text) > _COVER_TITLE_MAX_CHARS:
                        continue
                    by_size.setdefault(round(span["size"], 1), []).append(text)

        for size, parts in by_size.items():
            if size > best_size:
                best_size, best_parts = size, parts

    return best_parts


class _Section:
    """An outline entry with its page range and nested subsections."""

    def __init__(self, title: str, level: int, start_page: int) -> None:
        self.title = title
        self.level = level
        self.start_page = start_page
        self.end_page = start_page
        self.children: list["_Section"] = []


def _from_outline(doc: fitz.Document, book_title: str = "") -> list[Chapter]:
    """Extract chapters from the PDF's bookmark/outline tree."""
    toc = doc.get_toc()  # list of [level, title, page_number]
    if not toc:
        return []

    sections = _build_outline_tree(toc, len(doc))
    selected = _select_outline_level(sections)
    if len(selected) < 2:
        return []

    chapters = []
    index = 0
    for title, start_page, end_page in _split_oversized(doc, selected):
        text = _extract_page_range(doc, start_page, end_page)
        if not text.strip():
            continue
        if should_skip_chapter(title, text, book_title):
            continue
        if index == 0 and _is_front_matter(title, text, book_title):
            continue
        images = _extract_images_from_pages(doc, start_page, end_page)
        chapters.append(Chapter(
            title=title, text=text, index=index, images=images,
        ))
        index += 1

    return chapters


def _build_outline_tree(toc: list[Any], page_count: int) -> list[_Section]:
    """Nest the flat TOC by level and fill in page ranges. Returns sections in TOC order."""
    flat: list[_Section] = []
    roots: list[_Section] = []
    stack: list[_Section] = []

    for level, title, page in toc:
        section = _Section(title, level, max(page - 1, 0))
        while stack and stack[-1].level >= level:
            stack.pop()
        siblings = stack[-1].children if stack else roots
        siblings.append(section)
        stack.append(section)
        flat.append(section)

    _close_page_ranges(roots, page_count)
    return flat


def _close_page_ranges(sections: list[_Section], parent_end: int) -> None:
    """A section runs until its next sibling starts, or until its parent ends."""
    for i, section in enumerate(sections):
        section.end_page = (
            sections[i + 1].start_page if i + 1 < len(sections) else parent_end
        )
        _close_page_ranges(section.children, section.end_page)


def _select_outline_level(sections: list[_Section]) -> list[_Section]:
    """Pick the outline level that holds the book's chapters."""
    level1 = [s for s in sections if s.level == 1]
    level2 = [s for s in sections if s.level == 2]

    def is_chapter(section: _Section) -> bool:
        return bool(re.match(r"^chapter\s+", section.title, re.IGNORECASE))

    has_parts = any(re.match(r"^part\s+", s.title, re.IGNORECASE) for s in level1)
    if any(is_chapter(s) for s in level2):
        # Use only "Chapter N" entries — skip preface/appendix sub-sections
        return [s for s in level2 if is_chapter(s)]
    if level2 and has_parts:
        return level2
    if len(level1) >= 2:
        return level1
    return level2


def _split_oversized(
    doc: fitz.Document, sections: list[_Section], parent_title: str = "",
) -> list[tuple[str, int, int]]:
    """Flatten sections to (title, start_page, end_page), splitting big ones by subsection.

    A chapter far larger than the rest of the book (a "3. A long and illustrious
    history" that spans a third of the pages) makes the LLM drop most of its
    content, so it becomes one chapter per subsection instead.
    """
    segments: list[tuple[str, int, int]] = []

    for section in sections:
        title = _qualified_title(parent_title, section.title)
        text = _extract_page_range(doc, section.start_page, section.end_page)
        if len(text) <= MAX_CHAPTER_CHARS or not _can_subdivide(section):
            segments.append((title, section.start_page, section.end_page))
            continue

        # Text before the first subsection (a chapter intro) stays under the parent
        first_child = section.children[0]
        if first_child.start_page > section.start_page:
            segments.append((title, section.start_page, first_child.start_page))
        segments.extend(_split_oversized(doc, section.children, title))

    return segments


def _can_subdivide(section: _Section) -> bool:
    """True if some level below this section splits it into more than one piece."""
    if len(section.children) >= 2:
        return True
    # A lone subsection adds nothing by itself, but its own children may
    return bool(section.children) and _can_subdivide(section.children[0])


def _qualified_title(parent_title: str, title: str) -> str:
    """Prefix a subsection with its parent chapter unless it already says so."""
    title = title.strip()
    parent = parent_title.strip()
    if not parent:
        return title
    number = re.match(r"^\d+(\.\d+)*", parent)
    if number and title.startswith(number.group(0) + "."):
        return title  # "3. A long history" → "3.2 Britain since 1945"
    if title.lower().startswith(parent.lower()):
        return title
    return f"{parent} — {title}"


def _is_front_matter(title: str, text: str, book_title: str) -> bool:
    """The opening outline entry named after the book is a cover/contents page."""
    if not book_title or title.strip().lower() != book_title.strip().lower():
        return False
    return len(text) < _FRONT_MATTER_MAX_CHARS


def _detect_body_size(doc: fitz.Document) -> float:
    """Detect the most common (body) font size from a sample of pages."""
    from collections import Counter
    sizes: Counter[float] = Counter()
    sample_pages = range(min(10, len(doc)), min(30, len(doc)))
    for page_num in sample_pages:
        for block in doc[page_num].get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if len(span["text"].strip()) > 20:
                        sizes[round(span["size"], 1)] += 1
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _collapse_spaced(text: str) -> str:
    """Collapse spaced-out text like 'R E W I R E D' -> 'REWIRED'."""
    if len(text) < 5:
        return text
    # Check if most chars are followed by a space
    spaced = sum(1 for i in range(0, len(text) - 1, 2) if text[i] != " " and (i + 1 >= len(text) or text[i + 1] == " "))
    non_space = sum(1 for c in text if c != " ")
    if non_space >= 2 and spaced >= non_space * 0.6:
        return text.replace(" ", "")
    return text


def _from_heuristics(doc: fitz.Document) -> list[Chapter]:
    """Detect chapters by scanning for large/bold text that stands out from body text."""
    body_size = _detect_body_size(doc)
    heading_min = body_size * 1.25
    boundaries: list[tuple[int, str]] = []

    # Collect page header text (small bold text repeated across many pages)
    header_counts: dict[str, int] = {}
    for page_num in range(len(doc)):
        seen_on_page: set[str] = set()
        for block in doc[page_num].get_text("dict")["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text or span["size"] >= heading_min:
                        continue
                    collapsed = _collapse_spaced(text).lower()
                    # Only track multi-word or long spans as potential headers
                    # to avoid catching common words like "the", "of"
                    if len(collapsed) >= 5 and collapsed not in seen_on_page:
                        seen_on_page.add(collapsed)
                        header_counts[collapsed] = header_counts.get(collapsed, 0) + 1

    # Text appearing on 10%+ of pages is a running header
    page_count = len(doc)
    headers = {t for t, c in header_counts.items() if c >= max(3, page_count * 0.1)}

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        page_headings: list[str] = []

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text or len(text) > 100:
                        continue

                    size = span["size"]
                    is_bold = "bold" in span["font"].lower()

                    # Skip running headers
                    collapsed = _collapse_spaced(text).lower()
                    if collapsed in headers:
                        continue

                    # Pattern match (works at any size if bold)
                    if (size >= 16 or is_bold) and _matches_chapter_pattern(text):
                        if not boundaries or boundaries[-1][0] != page_num:
                            boundaries.append((page_num, text))
                            page_headings = []
                        break

                    # Size-based detection: large bold text
                    if size >= heading_min and is_bold:
                        page_headings.append(text)

        # If we found large heading text but no pattern match,
        # use it as a chapter boundary
        if page_headings and (not boundaries or boundaries[-1][0] != page_num):
            title = " ".join(page_headings)
            # Clean up soft hyphens and extra whitespace
            title = title.replace("\xad", "").replace("  ", " ").strip()
            if len(title) >= 3:
                boundaries.append((page_num, title))

    if len(boundaries) < 2:
        return []

    chapters = []
    index = 0
    for i, (start_page, title) in enumerate(boundaries):
        end_page = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(doc)
        text = _extract_page_range(doc, start_page, end_page)
        if not text.strip():
            continue
        if should_skip_chapter(title, text):
            continue
        images = _extract_images_from_pages(doc, start_page, end_page)
        chapters.append(Chapter(
            title=title, text=text, index=index, images=images,
        ))
        index += 1

    return chapters


def _from_fixed_chunks(doc: fitz.Document) -> list[Chapter]:
    """Fall back to splitting by fixed page chunks."""
    chapters = []
    total_pages = len(doc)
    index = 0

    for start in range(0, total_pages, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, total_pages)
        text = _extract_page_range(doc, start, end)
        if text.strip():
            title = f"Pages {start + 1}-{end}"
            chapters.append(Chapter(title=title, text=text, index=index))
            index += 1

    return chapters


def _matches_chapter_pattern(text: str) -> bool:
    return any(p.match(text) for p in CHAPTER_PATTERNS)


def _extract_page_range(doc: fitz.Document, start: int, end: int) -> str:
    parts = []
    for page_num in range(start, end):
        if page_num < len(doc):
            parts.append(doc[page_num].get_text())
    return "\n".join(parts)


def _find_caption_near_image(
    page: fitz.Page, img_rect: fitz.Rect,
) -> str:
    """Find figure caption text near an image on the page."""
    blocks = page.get_text("blocks")
    for block in blocks:
        bx0, by0, bx1, by1, text, _, _ = block
        if by0 < img_rect.y1:
            continue
        if by0 - img_rect.y1 > 60:
            break
        text = str(text).strip()
        if _FIGURE_RE.match(text) and len(text) < 300:
            return text
    return ""


def _extract_images_from_pages(
    doc: fitz.Document, start: int, end: int,
) -> list[BookImage]:
    """Extract images from a page range with captions."""
    images: list[BookImage] = []
    seen_xrefs: set[int] = set()

    for page_num in range(start, min(end, len(doc))):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        for img_info in image_list:
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue
            if not base_image:
                continue

            data = base_image["image"]
            if len(data) < _MIN_IMAGE_BYTES:
                continue

            ext = base_image.get("ext", "png")

            img_rects = page.get_image_rects(xref)
            caption = ""
            if img_rects:
                caption = _find_caption_near_image(page, img_rects[0])
            if not caption:
                continue

            img_id = f"book-img-{len(images) + 1}"
            images.append(BookImage(
                id=img_id, data=data, ext=ext, caption=caption,
            ))

    return images
