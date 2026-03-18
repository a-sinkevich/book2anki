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


class TestWrappedPartsNoGrouping:
    """Bauer-style: Book > Parts > Chapters as leaves — chapters keep own titles."""

    def test_chapters_not_grouped_under_parts(self):
        """Chapters in separate files under Parts should keep own titles."""
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
        assert result["ch1.html"] == "Chapter 1"
        assert result["ch2.html"] == "Chapter 2"
        assert result["ch3.html"] == "Chapter 3"
        assert result["ch4.html"] == "Chapter 4"
        assert result["ch5.html"] == "Chapter 5"
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
    """Dubynin-style: parent entries with same-file children, mixed with sibling leaves."""

    def test_leaves_after_same_file_parent_not_grouped_across_files(self):
        """Leaves in different files should NOT be grouped under a preceding parent."""
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
        assert result["a.html"] == "Topic A"
        assert result["b.html"] == "Topic B"
        assert result["c.html"] == "Topic C"

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
        assert result["a.html"] == "Section A"

    def test_no_sibling_grouping_when_children_in_different_files(self):
        """When children are in separate files, siblings should NOT be grouped."""
        book = _book_with_toc([
            _parent("Part I", "p1.html", [
                _link("Chapter 1", "ch1.html"),
                _link("Chapter 2", "ch2.html"),
            ]),
            _link("Part II", "p2.html"),
        ])
        result = _extract_toc_titles(book)
        # Part II should NOT be grouped under Part I
        assert result["p2.html"] == "Part II"


class TestSkipTitleHandling:
    """Skip-title parents should not group their children or siblings."""

    def test_skip_title_parent_children_keep_own_titles(self):
        """Children of 'Introduction' (a skip title) keep their own titles."""
        book = _book_with_toc([
            _parent("Introduction", "intro.html", [
                _link("Background", "bg.html"),
                _link("Overview", "ov.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["bg.html"] == "Background"
        assert result["ov.html"] == "Overview"

    def test_skip_title_parent_russian(self):
        """Russian skip title 'Введение' should not group children."""
        book = _book_with_toc([
            _parent("Введение", "intro.html", [
                _link("Что будет дальше", "next.html"),
            ]),
        ])
        result = _extract_toc_titles(book)
        assert result["next.html"] == "Что будет дальше"

    def test_skip_title_sibling_not_grouped(self):
        """Leaves with skip titles should not be absorbed by preceding parent."""
        book = _book_with_toc([
            _parent("Chapter 10", "ch10.html", [
                _link("Last section", "ch10.html#end"),
            ]),
            _link("Bibliography", "bib.html"),
            _link("Notes", "notes.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["bib.html"] == "Bibliography"
        assert result["notes.html"] == "Notes"

    def test_non_skip_sibling_keeps_own_title(self):
        """Siblings in different files keep their own titles."""
        book = _book_with_toc([
            _parent("Chapter 5", "ch5.html", [
                _link("Start", "ch5.html#1"),
            ]),
            _link("Topic X", "x.html"),
            _link("Acknowledgments", "ack.html"),
        ])
        result = _extract_toc_titles(book)
        assert result["x.html"] == "Topic X"
        assert result["ack.html"] == "Acknowledgments"


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
