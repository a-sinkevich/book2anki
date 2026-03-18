from pathlib import Path
from typing import Any

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from book2anki.models import Chapter, SKIP_TITLES, MIN_CHAPTER_LENGTH, should_skip_chapter


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
                    # Skip-titled section — map itself, let children keep
                    # their own titles, but mark subsequent siblings for
                    # skipping via level_group.
                    if href and href not in toc_map:
                        toc_map[href] = title or ""
                    walk_toc(children, group_title=None, depth=depth + 1)
                    level_group = title
                    level_group_href = None  # apply to any file
                    continue

                if has_subtree:
                    if href and href not in toc_map:
                        toc_map[href] = title or ""
                    walk_toc(children, group_title=None, depth=depth + 1)
                    level_group = None
                    level_group_href = None
                else:
                    is_skip = _is_skip_title(title)
                    gt = title if (title and not is_skip) else None
                    if href and href not in toc_map:
                        toc_map[href] = title or ""

                    child_hrefs = {
                        c.href.split("#")[0]
                        for c in children
                        if hasattr(c, "href") and not isinstance(c, tuple)
                    }
                    same_file = child_hrefs <= {href}

                    # Group children under parent when they share the
                    # parent's file (inline sub-headings) or at deep
                    # nesting (chapter > section).  Depth-1 parents
                    # with children in separate files are Parts, not
                    # chapters, so their children keep own titles.
                    child_gt = gt if (depth > 1 or same_file) else None
                    walk_toc(children, group_title=child_gt, depth=depth + 1)

                    # Sibling merging only when children are in the
                    # same file as the parent.
                    if same_file:
                        level_group = gt
                        level_group_href = href
                    else:
                        level_group = None
                        level_group_href = None
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


def _extract_chapters(book: epub.EpubBook, toc_titles: dict[str, str], book_title: str = "") -> list[Chapter]:
    """Extract chapters from the spine, using TOC titles when available.

    Items whose TOC titles were grouped under a parent chapter
    are merged into a single Chapter. When a TOC entry points to an
    empty/placeholder file, its title carries forward to the next
    content-bearing spine item.
    """
    chapter_texts: dict[str, list[str]] = {}
    chapter_order: list[str] = []
    unnamed_count = 0
    pending_title: str | None = None
    empty_toc_titles: list[str] = []

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        text = _html_to_text(item.get_content())
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
            chapter_order.append(title)
        chapter_texts[title].append(text)

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

    chapters = []
    index = 0
    for title in chapter_order:
        combined = "\n\n".join(chapter_texts[title])
        if should_skip_chapter(title, combined, book_title=book_title):
            continue
        combined = _strip_references(combined)
        chapters.append(Chapter(title=title, text=combined, index=index))
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
