import os
import posixpath
import re
from pathlib import Path
from typing import Any

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Tag

from book2anki.models import BookImage, Chapter, SKIP_TITLES, MIN_CHAPTER_LENGTH, should_skip_chapter

_MIN_IMAGE_BYTES = 5000  # skip icons/spacers smaller than 5KB
_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def _read_epub_safe(filepath: str) -> epub.EpubBook:
    """Read an EPUB file, tolerating missing files referenced in the manifest."""
    try:
        return epub.read_epub(filepath, options={"ignore_ncx": False})
    except KeyError:
        # Some EPUBs reference files in their manifest that don't exist in the archive.
        # Patch ebooklib's reader to skip missing files and retry.
        original_read_file = epub.EpubReader.read_file

        def _tolerant_read_file(self: Any, name: str) -> bytes:
            try:
                result: bytes = original_read_file(self, name)
                return result
            except KeyError:
                print(f"Warning: Skipping missing file in EPUB: {name}")
                return b""

        epub.EpubReader.read_file = _tolerant_read_file  # type: ignore[assignment]
        try:
            return epub.read_epub(filepath, options={"ignore_ncx": False})
        finally:
            epub.EpubReader.read_file = original_read_file  # type: ignore[assignment]


def parse_epub(filepath: str) -> tuple[str, list[Chapter]]:
    """Parse an EPUB file and return (book_title, chapters)."""
    book = _read_epub_safe(filepath)

    title = book.get_metadata("DC", "title")
    book_title = title[0][0] if title else _title_from_filename(filepath)

    toc_titles = _extract_toc_titles(book)
    chapters = _extract_chapters(book, toc_titles, book_title)

    if not chapters:
        full_text = _extract_all_text(book)
        if full_text.strip():
            chapters = [Chapter(title=book_title, text=full_text, index=0)]
            print("Warning: No chapter structure found, treating entire book as one chapter.")

    return book_title, chapters


def _title_from_filename(filepath: str) -> str:
    return Path(filepath).stem.replace("-", " ").replace("_", " ").title()


_NUMBERED_CHAPTER_RE = re.compile(
    r"^(\d+[\.\s:]|chapter\s|глава\s|раздел\s|лекция\s)",
    re.IGNORECASE,
)

_PART_WRAPPER_RE = re.compile(
    r"^(part\s|часть\s|teil\s|partie\s|parte\s)",
    re.IGNORECASE,
)


def _is_numbered_chapter(title: str | None) -> bool:
    """Return True if title looks like a numbered chapter heading.

    Matches "1. Title", "Chapter N", "Глава N", etc. — titles that
    indicate a real chapter whose sub-sections should be merged.
    """
    if not title:
        return False
    return bool(_NUMBERED_CHAPTER_RE.match(title.strip()))


def _extract_toc_titles(book: epub.EpubBook) -> dict[str, str]:
    """Build a map of item href -> chapter title from the TOC.

    When the TOC has hierarchy (chapters with sub-sections), sub-section
    hrefs are mapped to their parent chapter title so they get merged.
    """
    toc_map: dict[str, str] = {}

    def _is_skip_title(title: str | None) -> bool:
        if not title:
            return False
        t = title.lower().strip()
        return any(s in t for s in SKIP_TITLES)

    def walk_toc(
        items: list[Any], group_title: str | None = None, depth: int = 0,
    ) -> None:
        # level_group tracks the most recent PARENT at this level,
        # so sibling leaves after it get grouped under the same chapter.
        # level_group_href tracks which file the group applies to — only
        # merge siblings that share the same file.
        level_group = group_title
        level_group_href: str | None = None

        for item in items:
            if isinstance(item, tuple):
                section, children = item
                title = section.title if hasattr(section, "title") else None
                href = section.href.split("#")[0] if hasattr(section, "href") else None

                has_subtree = any(isinstance(c, tuple) for c in children)

                if _is_skip_title(title):
                    # Skip-titled section — group children under it
                    # so they all get skipped together.
                    if href and href not in toc_map:
                        toc_map[href] = title or ""
                    walk_toc(children, group_title=title, depth=depth + 1)
                    level_group = title
                    level_group_href = None  # apply to any file
                    continue

                if has_subtree:
                    if href and href not in toc_map:
                        toc_map[href] = title or ""
                    walk_toc(children, group_title=title, depth=depth + 1)
                    is_chapter = _is_numbered_chapter(title)
                    level_group = title
                    level_group_href = None if is_chapter else href
                else:
                    is_skip = _is_skip_title(title)
                    is_chapter = _is_numbered_chapter(title)
                    is_part = bool(title and _PART_WRAPPER_RE.match(title.strip()))
                    gt = title if (title and not is_skip) else None

                    # Don't register Part's href — let child chapters claim it
                    if href and href not in toc_map and not is_part:
                        toc_map[href] = title or ""

                    child_hrefs = {
                        c.href.split("#")[0]
                        for c in children
                        if hasattr(c, "href") and not isinstance(c, tuple)
                    }
                    same_file = child_hrefs <= {href}

                    # Group children under parent when they share the
                    # parent's file (inline sub-headings) or at deep
                    # nesting (chapter > section).  Parts ("Часть",
                    # "Part") always let children keep their own titles.
                    # At depth 0, only numbered chapters group children.
                    child_gt = gt if (not is_part and (depth > 0 or same_file or is_chapter)) else None
                    walk_toc(children, group_title=child_gt, depth=depth + 1)

                    # Group subsequent leaf siblings under this parent.
                    # Numbered chapters group across files (subsections);
                    # Parts/wrappers only group same-file siblings.
                    level_group = None if is_part else gt
                    level_group_href = None if is_chapter else href
            elif hasattr(item, "href"):
                href = item.href.split("#")[0]
                if href not in toc_map:
                    # level_group_href=None means "apply to any file" (skip section)
                    if level_group and (level_group_href is None or href == level_group_href):
                        toc_map[href] = level_group
                    else:
                        toc_map[href] = item.title
                        level_group = None
                        level_group_href = None

    walk_toc(book.toc)
    return toc_map


def _build_image_map(book: epub.EpubBook) -> dict[str, Any]:
    """Build a lookup from href (and basename) to image items."""
    img_map: dict[str, Any] = {}
    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        img_map[item.get_name()] = item
        basename = os.path.basename(item.get_name())
        if basename not in img_map:
            img_map[basename] = item
    return img_map


_FIGURE_PREFIXES = (
    "fig", "рис", "figure", "рисунок", "diagram", "схема",
    "table", "таблица", "chart", "график",
)

_FIGURE_CONTEXT_PATTERNS = (
    "на рисунке", "на рис.", "на схеме", "на графике",
    "на диаграмме", "на карте", "показан", "изображен",
    "in the figure", "in the diagram", "shown in", "illustrated",
)


def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def _extract_image_caption(img_tag: Tag) -> str:
    """Extract caption from an <img> tag's context.

    Combines surrounding paragraph text to describe the image.
    """
    alt = img_tag.get("alt", "") or ""
    if isinstance(alt, list):
        alt = " ".join(alt)
    if alt.lower().strip() in ("", "cover", "image", "img"):
        alt = ""

    # 1. <figcaption> inside <figure>
    figure = img_tag.find_parent("figure")
    if figure:
        figcaption = figure.find("figcaption")
        if figcaption:
            caption = figcaption.get_text(strip=True)
            if caption:
                return caption

    # 2. Caption sibling inside the same container as <img>
    #    e.g. <div class="full_img"><img/><p class="PodRis">Рис. 2.3...</p></div>
    for sib in img_tag.find_next_siblings():
        if not sib.name or sib.name not in ("p", "div", "span"):
            continue
        text = sib.get_text(strip=True)
        if not text:
            continue
        text_lower = text.lower()
        if any(text_lower.startswith(p) for p in _FIGURE_PREFIXES):
            # Collect continuation lines (multi-paragraph captions)
            cap_parts = [text]
            for cont in sib.find_next_siblings():
                if not cont.name or cont.name not in ("p", "span"):
                    break
                ct = cont.get_text(strip=True)
                if not ct:
                    break
                ct_lower = ct.lower()
                if any(ct_lower.startswith(p) for p in _FIGURE_PREFIXES):
                    break
                cap_parts.append(ct)
            return " ".join(cap_parts)

    parent = img_tag.parent
    if not parent:
        return alt

    # 3. Next sibling of parent starting with "Figure/Рис."
    sibling = parent.find_next_sibling()
    if sibling and sibling.name in ("p", "div", "span"):
        text = sibling.get_text(strip=True)
        if text and len(text) < 500:
            text_lower = text.lower()
            if any(text_lower.startswith(p) for p in _FIGURE_PREFIXES):
                return text

    # 4. Combine before + after paragraphs for context
    parts: list[str] = []

    prev = parent.find_previous_sibling()
    if prev and prev.name in ("p", "div"):
        text = prev.get_text(strip=True)
        if text and len(text) >= 20:
            parts.append(_truncate(text))

    if sibling and sibling.name in ("p", "div"):
        text = sibling.get_text(strip=True)
        if text and len(text) >= 20:
            parts.append(_truncate(text))

    if parts:
        return " | ".join(parts)

    return alt


def _extract_images_from_html(
    html_content: bytes, item_name: str, image_map: dict[str, Any],
) -> list[BookImage]:
    """Extract images from an HTML document with captions."""
    soup = BeautifulSoup(html_content, "html.parser")
    images: list[BookImage] = []
    seen_hrefs: set[str] = set()

    for img_tag in soup.find_all("img"):
        src = img_tag.get("src", "")
        if isinstance(src, list):
            src = src[0] if src else ""
        if not src:
            continue

        base_dir = posixpath.dirname(item_name)
        resolved = posixpath.normpath(posixpath.join(base_dir, src))
        basename = os.path.basename(src)

        img_item = image_map.get(resolved) or image_map.get(basename)
        if not img_item:
            continue

        href = img_item.get_name()
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        data = img_item.get_content()
        if len(data) < _MIN_IMAGE_BYTES:
            continue

        media_type = img_item.media_type or ""
        ext = _MIME_TO_EXT.get(media_type, "")
        if not ext:
            ext_from_name = os.path.splitext(href)[1].lstrip(".")
            ext = ext_from_name if ext_from_name else "png"

        caption = _extract_image_caption(img_tag)
        if not caption:
            continue

        img_id = f"book-img-{len(images) + 1}"
        images.append(BookImage(id=img_id, data=data, ext=ext, caption=caption))

    return images


def _extract_chapters(book: epub.EpubBook, toc_titles: dict[str, str], book_title: str = "") -> list[Chapter]:
    """Extract chapters from the spine, using TOC titles when available.

    Items whose TOC titles were grouped under a parent chapter
    are merged into a single Chapter. When a TOC entry points to an
    empty/placeholder file, its title carries forward to the next
    content-bearing spine item.
    """
    image_map = _build_image_map(book)
    chapter_texts: dict[str, list[str]] = {}
    chapter_images: dict[str, list[BookImage]] = {}
    chapter_order: list[str] = []
    unnamed_count = 0
    pending_title: str | None = None
    empty_toc_titles: list[str] = []

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content()
        text = _html_to_text(content)
        href = item.get_name()
        title = toc_titles.get(href)

        if title and len(text.strip()) < 100:
            pending_title = title
            empty_toc_titles.append(title)
            continue

        if not text.strip():
            continue

        if pending_title and not title:
            title = pending_title
            pending_title = None
            empty_toc_titles.pop()

        if title is None:
            unnamed_count += 1
            title = f"Section {unnamed_count}"

        if title not in chapter_texts:
            chapter_texts[title] = []
            chapter_images[title] = []
            chapter_order.append(title)
        chapter_texts[title].append(text)

        images = _extract_images_from_html(content, href, image_map)
        chapter_images[title].extend(images)

    # If empty TOC entries came AFTER their content in the spine,
    # match remaining titles with unnamed substantial content items
    if empty_toc_titles:
        unnamed_keys = [
            t for t in chapter_order
            if t.startswith("Section ")
            and len("\n\n".join(chapter_texts[t])) >= MIN_CHAPTER_LENGTH
        ]
        for i, new_title in enumerate(empty_toc_titles):
            if i < len(unnamed_keys):
                old_key = unnamed_keys[i]
                idx = chapter_order.index(old_key)
                chapter_order[idx] = new_title
                chapter_texts[new_title] = chapter_texts.pop(old_key)
                chapter_images[new_title] = chapter_images.pop(old_key, [])

    # Collect ALL images from every chapter (including skipped ones)
    # and make them available book-wide. Many books put all images
    # in a single "Illustrations" section rather than inline.
    all_images: list[BookImage] = []
    for title in chapter_order:
        all_images.extend(chapter_images.get(title, []))
    for i, img in enumerate(all_images):
        img.id = f"book-img-{i + 1}"

    chapters = []
    index = 0
    for title in chapter_order:
        combined = "\n\n".join(chapter_texts[title])
        if should_skip_chapter(title, combined, book_title=book_title):
            continue
        combined = _strip_references(combined)
        chapters.append(Chapter(
            title=title, text=combined, index=index, images=all_images,
        ))
        index += 1

    return chapters


def _html_to_text(html_content: bytes) -> str:
    """Strip HTML tags and return clean text."""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _strip_references(text: str) -> str:
    """Remove trailing references/bibliography section from chapter text."""
    for marker in ["References\n", "REFERENCES\n", "Bibliography\n"]:
        idx = text.rfind(marker)
        if idx > len(text) * 0.5:
            return text[:idx].rstrip()
    return text


def _extract_all_text(book: epub.EpubBook) -> str:
    """Extract all text from the book as a single string."""
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        text = _html_to_text(item.get_content())
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)
