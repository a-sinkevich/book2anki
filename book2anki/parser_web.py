import re
import ssl
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from book2anki.models import Chapter


def parse_url(url: str) -> tuple[str, list[Chapter]]:
    """Fetch a web page and return (page_title, [chapter])."""
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    title = _extract_title(soup, url)
    text = _extract_article_text(soup)

    if not text.strip():
        raise ValueError(f"No readable text found at {url}")

    chapters = [Chapter(title=title, text=text, index=0)]
    return title, chapters


def _fetch(url: str) -> bytes:
    """Fetch URL content with a browser-like User-Agent."""
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: bytes = resp.read()
            return data
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read()
                return data
        raise ValueError(f"Failed to fetch {url}: {e}") from e


def _extract_title(soup: BeautifulSoup, url: str) -> str:
    """Extract page title from HTML, falling back to URL."""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        title = re.split(r"\s*[|\-–—]\s*(?:Wikipedia|Medium|GitHub).*$", title)[0].strip()
        if title:
            return title

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text

    path = urlparse(url).path.strip("/").split("/")[-1]
    return path.replace("_", " ").replace("-", " ").title() or "Web Article"


def _extract_article_text(soup: BeautifulSoup) -> str:
    """Extract the main article text, stripping navigation and boilerplate."""
    for tag_name in ["script", "style", "nav", "header", "footer", "aside"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for cls in ["mw-editsection", "reflist", "navbox", "sidebar", "infobox"]:
        for tag in soup.find_all(class_=cls):
            tag.decompose()
    for elem_id in ["References", "External_links", "See_also", "Further_reading"]:
        for tag in soup.find_all(id=elem_id):
            tag.decompose()

    article = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_="mw-parser-output")  # Wikipedia
        or soup.find(id="mw-content-text")        # Wikipedia fallback
        or soup.find(class_="post-content")        # blogs
        or soup.find(class_="entry-content")       # WordPress
    )

    target = article if isinstance(article, Tag) else soup.body or soup
    return target.get_text(separator="\n", strip=True)
