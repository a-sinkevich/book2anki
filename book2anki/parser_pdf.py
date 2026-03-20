import re
from pathlib import Path

import fitz  # PyMuPDF

from book2anki.models import BookImage, Chapter, should_skip_chapter

_MIN_IMAGE_BYTES = 5000
_FIGURE_RE = re.compile(
    r"^(fig(ure|\.)|рис(унок|\.)|diagram|схема|table|таблица|chart|график)",
    re.IGNORECASE,
)

CHUNK_SIZE = 20  # pages per chunk in fallback mode

CHAPTER_PATTERNS = [
    re.compile(r"^chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^part\s+\d+", re.IGNORECASE),
    re.compile(r"^(introduction|conclusion|epilogue|prologue|preface|afterword)", re.IGNORECASE),
    re.compile(r"^\d+\.\s+\w", re.IGNORECASE),  # "1. Title"
    re.compile(r"^[IVXLC]+\.\s+\w"),  # Roman numerals
]


def parse_pdf(filepath: str) -> tuple[str, list[Chapter]]:
    """Parse a PDF file and return (book_title, chapters)."""
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

    chapters = _from_outline(doc)
    if not chapters:
        chapters = _from_heuristics(doc)
    if not chapters:
        chapters = _from_fixed_chunks(doc)
        print("Warning: No chapter structure detected, splitting by page chunks. "
              "Try the EPUB version if available.")

    doc.close()
    return book_title, chapters


def _extract_title(doc: fitz.Document, filepath: str) -> str:
    metadata = doc.metadata
    title = (metadata.get("title") or "").strip() if metadata else ""
    if title and not re.match(r"^[\d\-]+(\.\w+)?$", title) and "." not in title:
        return title
    return Path(filepath).stem.replace("-", " ").replace("_", " ").title()


def _from_outline(doc: fitz.Document) -> list[Chapter]:
    """Extract chapters from the PDF's bookmark/outline tree."""
    toc = doc.get_toc()  # list of [level, title, page_number]
    if not toc:
        return []

    level1 = [(title, page - 1) for level, title, page in toc if level == 1]
    level2 = [(title, page - 1) for level, title, page in toc if level == 2]

    has_parts = any(re.match(r"^part\s+", t, re.IGNORECASE) for t, _ in level1)
    has_chapter_l2 = any(re.match(r"^chapter\s+", t, re.IGNORECASE) for t, _ in level2)
    if level2 and (has_parts or has_chapter_l2):
        entries = level2
    elif len(level1) >= 2:
        entries = level1
    elif level2:
        entries = level2
    else:
        return []

    if len(entries) < 2:
        return []

    chapters = []
    index = 0
    for i, (title, start_page) in enumerate(entries):
        end_page = entries[i + 1][1] if i + 1 < len(entries) else len(doc)
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


def _from_heuristics(doc: fitz.Document) -> list[Chapter]:
    """Detect chapters by scanning for large/bold text matching chapter patterns."""
    boundaries: list[tuple[int, str]] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text or len(text) > 100:
                        continue

                    is_large = span["size"] >= 16
                    is_bold = "bold" in span["font"].lower()

                    if (is_large or is_bold) and _matches_chapter_pattern(text):
                        if not boundaries or boundaries[-1][0] != page_num:
                            boundaries.append((page_num, text))
                        break

    if len(boundaries) < 2:
        return []

    chapters = []
    for i, (start_page, title) in enumerate(boundaries):
        end_page = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(doc)
        text = _extract_page_range(doc, start_page, end_page)
        if text.strip():
            images = _extract_images_from_pages(doc, start_page, end_page)
            chapters.append(Chapter(
                title=title, text=text, index=i, images=images,
            ))

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
