from book2anki.models import should_skip_chapter
from book2anki.parser_pdf import (
    MAX_CHAPTER_CHARS,
    _build_outline_tree,
    _extract_title,
    _is_front_matter,
    _matches_chapter_pattern,
    _qualified_title,
    _select_outline_level,
    _split_oversized,
    _title_from_cover,
)


class FakePage:
    """A page whose text is a fixed size, optionally with sized title spans."""

    def __init__(self, chars=1000, spans=()):
        self._text = "x" * chars
        self._spans = spans

    def get_text(self, mode="text"):
        if mode != "dict":
            return self._text
        return {"blocks": [{
            "lines": [{
                "spans": [
                    {"text": text, "size": size, "font": "Helvetica-Bold"}
                    for text, size in self._spans
                ],
            }],
        }]}


class FakePdf:
    def __init__(self, pages, metadata=None):
        self._pages = pages
        self.metadata = metadata

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        return self._pages[index]


class TestShouldSkip:
    def test_skips_copyright(self):
        assert should_skip_chapter("Copyright", "x" * 5000)

    def test_skips_short_text(self):
        assert should_skip_chapter("Real Chapter", "short")

    def test_keeps_real_chapter(self):
        assert not should_skip_chapter("The Art of War", "x" * 5000)


class TestMatchesChapterPattern:
    def test_chapter_number(self):
        assert _matches_chapter_pattern("Chapter 1")
        assert _matches_chapter_pattern("CHAPTER 12")

    def test_numbered_title(self):
        assert _matches_chapter_pattern("1. Introduction")
        assert _matches_chapter_pattern("12. Advanced Topics")

    def test_part_number(self):
        assert _matches_chapter_pattern("Part 1")

    def test_roman_numeral(self):
        assert _matches_chapter_pattern("IV. The Empire")

    def test_no_match(self):
        assert not _matches_chapter_pattern("Just a title")
        assert not _matches_chapter_pattern("The 100 best things")


class TestExtractTitle:
    def test_rejects_isbn_title(self):
        class FakeDoc:
            metadata = {"title": "0321699750"}
            filepath = "Growing-Object-Oriented-Software.pdf"
        result = _extract_title(FakeDoc(), "Growing-Object-Oriented-Software.pdf")
        assert "Growing" in result

    def test_rejects_filename_title(self):
        class FakeDoc:
            metadata = {"title": "0321699750.pdf"}
        result = _extract_title(FakeDoc(), "My-Great-Book.pdf")
        assert "My Great Book" == result

    def test_uses_good_metadata_title(self):
        class FakeDoc:
            metadata = {"title": "Designing Data-Intensive Applications"}
        result = _extract_title(FakeDoc(), "ddia.pdf")
        assert result == "Designing Data-Intensive Applications"

    def test_no_metadata(self):
        class FakeDoc:
            metadata = None
        result = _extract_title(FakeDoc(), "some_book.pdf")
        assert result == "Some Book"

    def test_rejects_chapter_heading_metadata_title(self):
        # mkdocs/WeasyPrint exports carry the first chapter's page title
        doc = FakePdf(
            [FakePage(spans=[
                ("Life in the UK: A guide for", 36.0),
                ("new residents", 36.0),
                ("3rd Edition, PDF version", 13.7),
            ])],
            metadata={"title": "Chapter 1: The values and principles of the UK"},
        )
        assert _extract_title(doc, "Life-in-the-UK-Handbook.pdf") == (
            "Life in the UK: A guide for new residents"
        )

    def test_falls_back_to_filename_without_cover_title(self):
        doc = FakePdf([FakePage(spans=[("1. Introduction", 24.0)])],
                      metadata={"title": "Chapter 1: Intro"})
        assert _extract_title(doc, "My-Great-Book.pdf") == "My Great Book"


class TestTitleFromCover:
    def test_joins_wrapped_lines_of_largest_font(self):
        doc = FakePdf([FakePage(spans=[
            ("Small print", 8.0),
            ("The Art", 30.0),
            ("of War", 30.0),
        ])])
        assert _title_from_cover(doc) == "The Art of War"

    def test_ignores_chapter_heading(self):
        doc = FakePdf([FakePage(spans=[("Chapter 1: Beginnings", 28.0)])])
        assert _title_from_cover(doc) == ""

    def test_ignores_page_numbers(self):
        doc = FakePdf([FakePage(spans=[("42", 40.0)])])
        assert _title_from_cover(doc) == ""

    def test_survives_unreadable_doc(self):
        class Broken:
            def __len__(self):
                raise RuntimeError("damaged PDF")
        assert _title_from_cover(Broken()) == ""


class TestBuildOutlineTree:
    def test_nests_by_level_and_closes_ranges(self):
        toc = [
            [1, "1. First", 1],
            [2, "1.1 Sub", 2],
            [2, "1.2 Sub", 4],
            [1, "2. Second", 6],
        ]
        sections = _build_outline_tree(toc, page_count=10)

        first, sub1, sub2, second = sections
        assert [s.title for s in first.children] == ["1.1 Sub", "1.2 Sub"]
        assert (first.start_page, first.end_page) == (0, 5)
        assert (sub1.start_page, sub1.end_page) == (1, 3)
        assert (sub2.start_page, sub2.end_page) == (3, 5)  # last child ends with parent
        assert (second.start_page, second.end_page) == (5, 10)
        assert second.children == []

    def test_handles_skipped_levels(self):
        toc = [[1, "Part One", 1], [3, "Deep", 2]]
        sections = _build_outline_tree(toc, page_count=4)
        assert sections[0].children == [sections[1]]


class TestSelectOutlineLevel:
    def _sections(self, toc):
        return _build_outline_tree(toc, page_count=100)

    def test_prefers_level1_chapters(self):
        sections = self._sections([
            [1, "1. First", 1], [2, "1.1 Sub", 2], [1, "2. Second", 5],
        ])
        assert [s.title for s in _select_outline_level(sections)] == [
            "1. First", "2. Second",
        ]

    def test_uses_level2_under_parts(self):
        sections = self._sections([
            [1, "Part 1", 1], [2, "Opening moves", 2], [2, "Endgame", 5],
        ])
        assert [s.title for s in _select_outline_level(sections)] == [
            "Opening moves", "Endgame",
        ]

    def test_keeps_only_chapter_entries_at_level2(self):
        sections = self._sections([
            [1, "Front", 1], [2, "Preface notes", 2],
            [2, "Chapter 1", 4], [2, "Chapter 2", 8],
        ])
        assert [s.title for s in _select_outline_level(sections)] == [
            "Chapter 1", "Chapter 2",
        ]


class TestSplitOversized:
    def _doc(self, page_chars):
        return FakePdf([FakePage(chars=n) for n in page_chars])

    def test_keeps_small_chapter_whole(self):
        doc = self._doc([1000] * 4)
        sections = _build_outline_tree(
            [[1, "1. Small", 1], [2, "1.1 Sub", 2], [2, "1.2 Sub", 3]], 4,
        )
        assert _split_oversized(doc, [sections[0]]) == [("1. Small", 0, 4)]

    def test_splits_oversized_chapter_into_subsections(self):
        big = MAX_CHAPTER_CHARS  # two pages already exceed the limit
        doc = self._doc([big] * 4)
        sections = _build_outline_tree(
            [[1, "3. A long history", 1], [2, "3.1 Britain since 1945", 1],
             [2, "3.2 A global power", 3]], 4,
        )
        assert _split_oversized(doc, [sections[0]]) == [
            ("3.1 Britain since 1945", 0, 2),
            ("3.2 A global power", 2, 4),
        ]

    def test_keeps_chapter_intro_before_first_subsection(self):
        big = MAX_CHAPTER_CHARS
        doc = self._doc([big] * 4)
        sections = _build_outline_tree(
            [[1, "3. A long history", 1], [2, "3.1 Sub", 2], [2, "3.2 Sub", 3]], 4,
        )
        assert _split_oversized(doc, [sections[0]]) == [
            ("3. A long history", 0, 1),
            ("3.1 Sub", 1, 2),
            ("3.2 Sub", 2, 4),
        ]

    def test_needs_at_least_two_subsections_to_split(self):
        doc = self._doc([MAX_CHAPTER_CHARS] * 4)
        sections = _build_outline_tree(
            [[1, "3. A long history", 1], [2, "3.1 Only child", 2]], 4,
        )
        assert _split_oversized(doc, [sections[0]]) == [("3. A long history", 0, 4)]

    def test_splits_recursively_while_still_oversized(self):
        big = MAX_CHAPTER_CHARS
        doc = self._doc([big] * 4)
        sections = _build_outline_tree(
            [[1, "Chapter 3", 1], [2, "History", 1],
             [3, "The Romans", 1], [3, "The Vikings", 3]], 4,
        )
        assert _split_oversized(doc, [sections[0]]) == [
            ("Chapter 3 — History — The Romans", 0, 2),
            ("Chapter 3 — History — The Vikings", 2, 4),
        ]


class TestQualifiedTitle:
    def test_no_parent(self):
        assert _qualified_title("", "3.2 Britain since 1945") == "3.2 Britain since 1945"

    def test_keeps_title_numbered_under_parent(self):
        assert _qualified_title(
            "3. A long and illustrious history", "3.2 Britain since 1945",
        ) == "3.2 Britain since 1945"

    def test_prefixes_bare_subsection(self):
        assert _qualified_title("Chapter 5", "The Black Death") == (
            "Chapter 5 — The Black Death"
        )

    def test_does_not_repeat_parent(self):
        assert _qualified_title("The Tudors", "The Tudors and Stuarts") == (
            "The Tudors and Stuarts"
        )


class TestIsFrontMatter:
    def test_skips_short_cover_entry_named_after_book(self):
        assert _is_front_matter("Life in the UK", "x" * 1300, "Life in the UK")

    def test_keeps_long_section_named_after_book(self):
        assert not _is_front_matter("Life in the UK", "x" * 50000, "Life in the UK")

    def test_keeps_other_titles(self):
        assert not _is_front_matter("1. Values", "x" * 100, "Life in the UK")
