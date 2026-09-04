"""HTML to plain text for the EPUB and web parsers.

BeautifulSoup's `get_text(separator="\\n")` puts a line break at *every* string
boundary, inline tags included. On real books that shreds the text: a sentence
containing italics arrives split across three lines, and a syntax-highlighted
code listing arrives one token per line. Roughly half the lines of a DDIA
chapter came out as fragments that way.

This walks the tree instead. Block elements end a line, inline elements do not,
`<pre>` keeps its own whitespace, and author emphasis survives as `<em>` /
`<strong>` — the one place the source tells us which words carry the weight of
a sentence, which is worth far more to a card generator than the tags cost.
"""

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Elements that end the current line. Everything not listed here is treated as
# inline, so it stays inside the sentence it belongs to.
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}

# Emphasis is normalized to two markers rather than kept as-is: books use <i>
# and <em> interchangeably, and the distinction that matters is only weight.
_EMPHASIS_TAGS = {
    "em": "em", "i": "em", "cite": "em",
    "strong": "strong", "b": "strong",
}

_DROP_TAGS = {"script", "style", "head", "noscript", "template"}

# Whole paragraphs set in italic are a typographic convention — epigraphs, block
# quotes, passages in another language — not the author pointing at a phrase.
# Marking them would bury the short spans that actually carry signal.
_MAX_EMPHASIS_CHARS = 120

_INLINE_WS_RE = re.compile(r"\s+")


def html_to_text(markup: bytes | str | BeautifulSoup | Tag) -> str:
    """Render HTML as text, keeping sentences whole and emphasis visible."""
    if isinstance(markup, (BeautifulSoup, Tag)):
        root: BeautifulSoup | Tag = markup
    else:
        root = BeautifulSoup(markup, "html.parser")

    out: list[str] = []
    _render(root, out, in_pre=False)
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)      # trailing spaces on a line
    text = re.sub(r"\n{3,}", "\n\n", text)      # at most one blank line
    return text.strip()


def _render(node: BeautifulSoup | Tag, out: list[str], in_pre: bool) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = str(child)
            out.append(text if in_pre else _INLINE_WS_RE.sub(" ", text))
            continue
        if not isinstance(child, Tag):
            continue

        name = (child.name or "").lower()
        if name in _DROP_TAGS:
            continue
        if name == "br":
            out.append("\n")
            continue
        if name == "pre":
            out.append("\n")
            _render(child, out, in_pre=True)
            out.append("\n")
            continue

        marker = _EMPHASIS_TAGS.get(name)
        if marker and not in_pre and _is_marked_emphasis(child):
            out.append(f"<{marker}>")
            _render(child, out, in_pre)
            out.append(f"</{marker}>")
            continue

        if name in _BLOCK_TAGS:
            out.append("\n")
            _render(child, out, in_pre)
            out.append("\n")
            continue

        _render(child, out, in_pre)


def _is_marked_emphasis(tag: Tag) -> bool:
    """Whether this emphasis span is a phrase worth flagging, not page styling."""
    inner = tag.get_text(strip=True)
    return bool(inner) and len(inner) <= _MAX_EMPHASIS_CHARS
