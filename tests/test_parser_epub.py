from ebooklib import epub

from book2anki.models import should_skip_chapter
from book2anki.parser_epub import _html_to_text, _strip_references, _title_from_filename, parse_epub


class TestHtmlToText:
    def test_strips_layout_tags(self):
        html = b"<p>Hello <span class='x'>world</span></p>"
        assert _html_to_text(html) == "Hello world"

    def test_empty_html(self):
        assert _html_to_text(b"") == ""

    def test_nested_tags(self):
        html = b"<div><p><span>Text</span></p></div>"
        assert "Text" in _html_to_text(html)

    def test_drops_the_xml_declaration_and_doctype(self):
        html = b"<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE html>\n<html><body><p>Text</p></body></html>"
        assert _html_to_text(html) == "Text"


class TestShouldSkip:
    def test_skips_copyright(self):
        assert should_skip_chapter("Copyright", "x" * 5000)

    def test_skips_bibliography(self):
        assert should_skip_chapter("Bibliography", "x" * 5000)

    def test_skips_series_page(self):
        assert should_skip_chapter("Series", "x" * 5000)

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


class TestChapters:
    def _book(self, tmp_path, files, toc):
        """Write an EPUB of (file name, body) in reading order; `toc` names some."""
        book = epub.EpubBook()
        book.set_title("The Intellectual Life")
        book.set_language("en")
        items = {}
        for name, body in files:
            items[name] = epub.EpubHtml(file_name=name, content=f"<html><body>{body}</body></html>")
            book.add_item(items[name])
        book.toc = [epub.Link(name, title, name) for name, title in toc]
        book.add_item(epub.EpubNcx())
        book.spine = list(items.values())
        path = tmp_path / "book.epub"
        epub.write_epub(str(path), book)
        return str(path)

    def test_files_the_toc_leaves_out_are_titled_by_their_heading(self, tmp_path):
        prose = "<p>" + "To speak of vocation is to speak of a life. " * 40 + "</p>"
        path = self._book(tmp_path, [
            ("preface.xhtml", "<h1>Preface to the Third Edition</h1>" + prose),
            ("ch1.xhtml", "<h1>Chapter 1. <br/>The Intellectual Vocation</h1>" + prose),
            ("ch2.xhtml", "<h1>Chapter 2. <i>The Virtues</i></h1>" + prose),
            ("loose.xhtml", prose),
        ], toc=[("preface.xhtml", "THE INTELLECTUAL LIFE")])
        _, chapters = parse_epub(path)
        assert [c.title for c in chapters] == [
            "THE INTELLECTUAL LIFE",
            "Chapter 1. The Intellectual Vocation",
            "Chapter 2. The Virtues",
        ]
