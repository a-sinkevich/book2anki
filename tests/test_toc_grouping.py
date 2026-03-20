"""Tests for EPUB TOC grouping and chapter merging logic."""
from types import SimpleNamespace

from book2anki.parser_epub import _extract_toc_titles


def _link(title: str, href: str) -> SimpleNamespace:
    """Create a mock TOC leaf item."""
    return SimpleNamespace(title=title, href=href)


def _parent(title: str, href: str, children: list) -> tuple:
    """Create a mock TOC parent entry (section, children)."""
    section = SimpleNamespace(title=title, href=href)
    return (section, children)


def _book_with_toc(toc: list) -> SimpleNamespace:
    """Create a mock book with the given TOC."""
    return SimpleNamespace(toc=toc)


class TestFlatToc:
    """TOC with only leaf items — no grouping should happen."""

    def test_flat_leaves_keep_own_titles(self):
        book = _book_with_toc([
            _link("Chapter 1", "ch1.html"),
            _link("Chapter 2", "ch2.html"),
            _link("Chapter 3", "ch3.html"),
        ])
        result = _extract_toc_titles(book)
        assert result == {
            "ch1.html": "Chapter 1",
            "ch2.html": "Chapter 2",
            "ch3.html": "Chapter 3",
        }


class TestHierarchicalGrouping:
    """Kahneman-style: nested parts > chapters > sub-sections."""

    def test_children_grouped_under_parent_at_depth(self):
        """Sub-sections merge into their parent chapter when nested."""
        book = _book_with_toc([
            _parent("Book Title", "book.html", [
                _parent("Part I", "p1.html", [
                    _parent("Chapter 1", "ch1.html", [
                        _link("Section 1.1", "s1.html"),
                        _link("Section 1.2", "s2.html"),
                    ]),
                    _parent("Chapter 2", "ch2.html", [
                        _link("Section 2.1", "s3.html"),
                    ]),
                ]),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["s1.html"] == "Chapter 1"
        assert result["s2.html"] == "Chapter 1"
        assert result["s3.html"] == "Chapter 2"

    def test_parent_href_mapped_to_own_title(self):
        book = _book_with_toc([
            _parent("Chapter 1", "ch1.html", [
                _link("Sub A", "a.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["ch1.html"] == "Chapter 1"

    def test_intermediate_level_not_grouped(self):
        """Parts containing chapters — chapters should NOT merge into part."""
        book = _book_with_toc([
            _parent("Book Title", "book.html", [
                _parent("Part I", "p1.html", [
                    _parent("Chapter 1", "ch1.html", [
                        _link("Sec 1.1", "s1.html"),
                        _link("Sec 1.2", "s2.html"),
                    ]),
                    _parent("Chapter 2", "ch2.html", [
                        _link("Sec 2.1", "s3.html"),
                    ]),
                ]),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["s1.html"] == "Chapter 1"
        assert result["s2.html"] == "Chapter 1"
        assert result["s3.html"] == "Chapter 2"
        assert result["p1.html"] == "Part I"


class TestWrappedPartsGrouping:
    """Bauer-style: Book > Parts > Chapters as leaves — chapters group under parts."""

    def test_chapters_grouped_under_parts(self):
        """Chapters in separate files under Parts group under part title."""
        book = _book_with_toc([
            _parent("Book Title", "book.html", [
                _parent("Part I", "p1.html", [
                    _link("Chapter 1", "ch1.html"),
                    _link("Chapter 2", "ch2.html"),
                    _link("Chapter 3", "ch3.html"),
                ]),
                _parent("Part II", "p2.html", [
                    _link("Chapter 4", "ch4.html"),
                    _link("Chapter 5", "ch5.html"),
                ]),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["ch1.html"] == "Part I"
        assert result["ch2.html"] == "Part I"
        assert result["ch3.html"] == "Part I"
        assert result["ch4.html"] == "Part II"
        assert result["ch5.html"] == "Part II"
        assert result["p1.html"] == "Part I"
        assert result["p2.html"] == "Part II"


class TestRootLevelNoGrouping:
    """Root-level PARENTs with children in separate files should NOT group."""

    def test_book_title_children_keep_own_titles(self):
        """Medovnik-style: book title with chapter children."""
        book = _book_with_toc([
            _parent("My Book", "book.html", [
                _link("Chapter 1", "ch1.html"),
                _link("Chapter 2", "ch2.html"),
                _link("Chapter 3", "ch3.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["ch1.html"] == "Chapter 1"
        assert result["ch2.html"] == "Chapter 2"
        assert result["ch3.html"] == "Chapter 3"

    def test_parts_children_keep_own_titles(self):
        """Remnick-style: parts with chapter children."""
        book = _book_with_toc([
            _parent("Part I", "p1.html", [
                _link("Chapter 1", "ch1.html"),
                _link("Chapter 2", "ch2.html"),
            ]),
            _parent("Part II", "p2.html", [
                _link("Chapter 3", "ch3.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["ch1.html"] == "Chapter 1"
        assert result["ch2.html"] == "Chapter 2"
        assert result["ch3.html"] == "Chapter 3"

    def test_parts_own_hrefs_mapped(self):
        """Part entries themselves are still mapped."""
        book = _book_with_toc([
            _parent("Part I", "p1.html", [
                _link("Chapter 1", "ch1.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["p1.html"] == "Part I"


class TestSiblingGrouping:
    """Gazzali-style: parent entries with children, mixed with sibling leaves."""

    def test_leaves_after_parent_grouped(self):
        """Leaf siblings after a parent are grouped under it (subsections)."""
        book = _book_with_toc([
            _parent("Chapter 1", "ch1.html", [
                _link("Intro", "ch1.html#1"),
            ]),
            _link("Topic A", "a.html"),
            _link("Topic B", "b.html"),
            _parent("Chapter 2", "ch2.html", [
                _link("Intro", "ch2.html#1"),
            ]),
            _link("Topic C", "c.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["a.html"] == "Chapter 1"
        assert result["b.html"] == "Chapter 1"
        assert result["c.html"] == "Chapter 2"

    def test_leaves_before_first_parent_keep_own_titles(self):
        book = _book_with_toc([
            _link("Prologue", "pro.html"),
            _parent("Chapter 1", "ch1.html", [
                _link("Start", "ch1.html#1"),
            ]),
            _link("Section A", "a.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["pro.html"] == "Prologue"
        assert result["a.html"] == "Chapter 1"

    def test_sibling_after_part_keeps_own_title(self):
        """Leaf siblings after a Part parent keep their own titles."""
        book = _book_with_toc([
            _parent("Part I", "p1.html", [
                _link("Chapter 1", "ch1.html"),
                _link("Chapter 2", "ch2.html"),
            ]),
            _link("Part II", "p2.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["p2.html"] == "Part II"


class TestSkipTitleHandling:
    """Skip-title parents group their children for collective skipping."""

    def test_skip_title_parent_children_grouped(self):
        """Children of 'Acknowledgments' (a skip title) are grouped under it."""
        book = _book_with_toc([
            _parent("Acknowledgments", "ack.html", [
                _link("People", "people.html"),
                _link("Institutions", "inst.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["people.html"] == "Acknowledgments"
        assert result["inst.html"] == "Acknowledgments"

    def test_skip_title_parent_russian(self):
        """Russian skip title 'Благодарности' groups children for skipping."""
        book = _book_with_toc([
            _parent("Благодарности", "ack.html", [
                _link("Коллегам", "next.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["next.html"] == "Благодарности"

    def test_skip_title_sibling_grouped(self):
        """Leaves after a parent are grouped under it."""
        book = _book_with_toc([
            _parent("Chapter 10", "ch10.html", [
                _link("Last section", "ch10.html#end"),
            ]),
            _link("Bibliography", "bib.html"),
            _link("Notes", "notes.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["bib.html"] == "Chapter 10"
        assert result["notes.html"] == "Chapter 10"

    def test_non_skip_sibling_grouped_under_parent(self):
        """Siblings after a parent are grouped under it."""
        book = _book_with_toc([
            _parent("Chapter 5", "ch5.html", [
                _link("Start", "ch5.html#1"),
            ]),
            _link("Topic X", "x.html"),
            _link("Acknowledgments", "ack.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["x.html"] == "Chapter 5"
        assert result["ack.html"] == "Chapter 5"


class TestFragmentHandling:
    """Hrefs with #fragment anchors should be stripped to base filename."""

    def test_fragment_stripped(self):
        book = _book_with_toc([
            _link("Section A", "file.html#section-1"),
            _link("Section B", "file.html#section-2"),
        ])
        result = _extract_toc_titles(book)
        # First one wins since same base href
        assert result["file.html"] == "Section A"

    def test_parent_fragment_stripped(self):
        """Parent and child in the same file — child maps to parent's title."""
        book = _book_with_toc([
            _parent("Book", "book.html", [
                _parent("Chapter 1", "ch.html#top", [
                    _link("Sub", "ch.html#section1"),
                ]),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["ch.html"] == "Chapter 1"
