from book2anki.parser_web import _extract_title, _extract_article_text

from bs4 import BeautifulSoup


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestExtractTitle:
    def test_from_title_tag(self):
        soup = _soup("<html><head><title>My Article</title></head></html>")
        assert _extract_title(soup, "http://example.com") == "My Article"

    def test_strips_wikipedia_suffix(self):
        soup = _soup("<html><head><title>Spaced repetition - Wikipedia</title></head></html>")
        assert _extract_title(soup, "http://en.wikipedia.org/wiki/Spaced_repetition") == "Spaced repetition"

    def test_falls_back_to_h1(self):
        soup = _soup("<html><body><h1>My Heading</h1></body></html>")
        assert _extract_title(soup, "http://example.com") == "My Heading"

    def test_falls_back_to_url(self):
        soup = _soup("<html><body><p>No title here</p></body></html>")
        assert _extract_title(soup, "http://example.com/my-article") == "My Article"

    def test_empty_url_path(self):
        soup = _soup("<html><body></body></html>")
        assert _extract_title(soup, "http://example.com/") == "Web Article"


class TestExtractArticleText:
    def test_extracts_body_text(self):
        html = "<html><body><p>Hello world</p></body></html>"
        text = _extract_article_text(_soup(html))
        assert "Hello world" in text

    def test_strips_scripts_and_styles(self):
        html = "<html><body><script>var x=1;</script><style>.a{}</style><p>Content</p></body></html>"
        text = _extract_article_text(_soup(html))
        assert "Content" in text
        assert "var x" not in text
        assert ".a{}" not in text

    def test_strips_nav_header_footer(self):
        html = "<html><body><nav>Menu</nav><main><p>Article</p></main><footer>Footer</footer></body></html>"
        text = _extract_article_text(_soup(html))
        assert "Article" in text
        assert "Menu" not in text
        assert "Footer" not in text

    def test_prefers_article_tag(self):
        html = "<html><body><div>Sidebar</div><article><p>Main content</p></article></body></html>"
        text = _extract_article_text(_soup(html))
        assert "Main content" in text

    def test_prefers_main_tag(self):
        html = "<html><body><div>Other</div><main><p>Primary</p></main></body></html>"
        text = _extract_article_text(_soup(html))
        assert "Primary" in text
