from book2anki.models import should_skip_chapter
from book2anki.parser_epub import _html_to_text, _strip_references, _title_from_filename


class TestHtmlToText:
    def test_strips_tags(self):
        html = b"<p>Hello <b>world</b></p>"
        assert "Hello" in _html_to_text(html)
        assert "world" in _html_to_text(html)
        assert "<" not in _html_to_text(html)

    def test_empty_html(self):
        assert _html_to_text(b"") == ""

    def test_nested_tags(self):
        html = b"<div><p><span>Text</span></p></div>"
        assert "Text" in _html_to_text(html)


class TestShouldSkip:
    def test_skips_copyright(self):
        assert should_skip_chapter("Copyright", "x" * 5000)

    def test_skips_bibliography(self):
        assert should_skip_chapter("Bibliography", "x" * 5000)

    def test_skips_russian_titles(self):
        assert should_skip_chapter("Содержание", "x" * 5000)
        assert should_skip_chapter("Об авторе", "x" * 5000)
        assert should_skip_chapter("Предисловие", "x" * 5000)

    def test_skips_short_text(self):
        assert should_skip_chapter("Real Chapter", "short")

    def test_skips_section_prefix(self):
        assert should_skip_chapter("Section 5", "x" * 5000)

    def test_keeps_real_chapter(self):
        assert not should_skip_chapter("The Art of War", "x" * 5000)

    def test_case_insensitive(self):
        assert should_skip_chapter("COPYRIGHT", "x" * 5000)
        assert should_skip_chapter("Table of Contents", "x" * 5000)


class TestStripReferences:
    def test_strips_references_at_end(self):
        text = "A" * 1000 + "\nReferences\nSome ref 1\nSome ref 2"
        result = _strip_references(text)
        assert "References" not in result

    def test_keeps_references_in_first_half(self):
        text = "References\n" + "A" * 1000
        result = _strip_references(text)
        assert "References" in result

    def test_no_references(self):
        text = "Just normal text without any ref section"
        assert _strip_references(text) == text


class TestTitleFromFilename:
    def test_basic(self):
        assert _title_from_filename("/path/to/my-great-book.epub") == "My Great Book"

    def test_underscores(self):
        assert _title_from_filename("some_book_title.pdf") == "Some Book Title"
