from book2anki.models import should_skip_chapter
from book2anki.parser_pdf import _extract_title, _matches_chapter_pattern


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
