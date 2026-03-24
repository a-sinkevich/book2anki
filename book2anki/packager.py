import hashlib
import html
import os
import re
import sqlite3
import tempfile
import zipfile

import genanki

from book2anki.models import Card

_SAFE_TAGS = {"pre", "code", "/pre", "/code", "b", "/b", "br", "br/",
              "ul", "/ul", "ol", "/ol", "li", "/li", "p", "/p",
              "div", "/div",
              "strong", "/strong", "img",
              "svg", "/svg", "rect", "/rect", "circle", "/circle",
              "ellipse", "/ellipse", "line", "/line", "polyline", "/polyline",
              "polygon", "/polygon", "path", "/path", "text", "/text",
              "tspan", "/tspan", "g", "/g", "defs", "/defs",
              "marker", "/marker", "use", "/use",
              "linearGradient", "/linearGradient",  # noqa: N815
              "radialGradient", "/radialGradient",  # noqa: N815
              "stop", "/stop"}
_TAG_RE = re.compile(r"<(/?\w+)[^>]*>")


def _escape_field(text: str) -> str:
    """HTML-escape a field, preserving known safe HTML tags like <pre><code>."""
    text = html.unescape(text)
    parts = _TAG_RE.split(text)
    if len(parts) == 1:
        return html.escape(text)

    result: list[str] = []
    matches = list(_TAG_RE.finditer(text))
    last_end = 0
    for m in matches:
        result.append(html.escape(text[last_end:m.start()]))
        tag_name = m.group(1).lower()
        if tag_name in _SAFE_TAGS:
            result.append(m.group(0))
        else:
            result.append(html.escape(m.group(0)))
        last_end = m.end()
    result.append(html.escape(text[last_end:]))
    return "".join(result)


CARD_CSS = """\
.card {
    font-family: arial;
    font-size: 20px;
    text-align: left;
    color: black;
    background-color: white;
}
.card.night_mode {
    color: white;
    background-color: #1e1e1e;
}
pre {
    background-color: rgba(128, 128, 128, 0.12);
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 4px;
    padding: 8px 12px;
    overflow-x: auto;
    margin: 8px 0;
}
code {
    font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
    font-size: 16px;
}
.example {
    margin-top: 12px;
    padding-top: 8px;
    border-top: 1px dashed rgba(128, 128, 128, 0.4);
    font-size: 17px;
}
.image {
    margin-top: 12px;
    padding-top: 8px;
    border-top: 1px dashed rgba(128, 128, 128, 0.4);
    text-align: center;
}
.image img {
    max-width: 100%;
    height: auto;
}
.image svg {
    max-width: 100%;
    height: auto;
}
.image-caption {
    font-size: 16px;
    margin-top: 4px;
}
"""

_ANSWER_FMT = (
    '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>'
    '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
    '{{#Image}}<div class="image">{{Image}}</div>{{/Image}}'
)

CARD_MODEL = genanki.Model(
    model_id=1607392322,
    name="book2anki Basic",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Example"},
        {"name": "Image"},
        {"name": "Chapter"},
        {"name": "Book"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": _ANSWER_FMT,
        },
    ],
    css=CARD_CSS,
)

ARTICLE_MODEL = genanki.Model(
    model_id=1607392323,
    name="book2anki Article",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Example"},
        {"name": "Image"},
        {"name": "Article"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": _ANSWER_FMT,
        },
    ],
    css=CARD_CSS,
)

VOCAB_MODEL = genanki.Model(
    model_id=1607392325,
    name="book2anki Vocab",
    fields=[
        {"name": "Word"},
        {"name": "Context"},
        {"name": "Translation"},
        {"name": "Definition"},
        {"name": "Example"},
        {"name": "Book"},
        {"name": "Chapter"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": (
                '<div class="word">{{Word}}</div>'
                '<div class="context">{{Context}}</div>'
            ),
            "afmt": (
                '{{FrontSide}}<hr id="answer">'
                '<div class="translation">{{Translation}}</div>'
                '{{#Definition}}<div class="definition">{{Definition}}</div>{{/Definition}}'
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
            ),
        },
    ],
    css=CARD_CSS + """\
.word {
    font-size: 26px;
    font-weight: bold;
    margin-bottom: 8px;
}
.ipa {
    font-size: 16px;
    font-weight: normal;
    color: #888;
    margin-top: 2px;
}
.card.night_mode .ipa {
    color: #777;
}
.context {
    font-size: 18px;
    color: #555;
    font-style: normal;
}
.card.night_mode .context {
    color: #aaa;
}
.translation {
    font-size: 22px;
    margin-bottom: 6px;
}
.definition {
    font-size: 17px;
    color: #666;
    margin-top: 8px;
    padding-top: 6px;
    border-top: 1px dashed rgba(128, 128, 128, 0.4);
}
.card.night_mode .definition {
    color: #999;
}
.example {
    color: #666;
}
.card.night_mode .example {
    color: #999;
}
.etymology {
    font-size: 14px;
    color: #888;
    margin-top: 4px;
}
.sep {
    height: 1px;
    background: rgba(128, 128, 128, 0.3);
    margin: 6px 0;
}
.card.night_mode .etymology {
    color: #777;
}
""",
)

YOUTUBE_MODEL = genanki.Model(
    model_id=1607392324,
    name="book2anki YouTube",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Example"},
        {"name": "Image"},
        {"name": "Video"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": _ANSWER_FMT,
        },
    ],
    css=CARD_CSS,
)


def _group_cards_by_chapter(cards: list[Card]) -> list[tuple[str, list[Card]]]:
    """Group cards by chapter title, preserving order."""
    chapters: dict[str, list[Card]] = {}
    for card in cards:
        chapters.setdefault(card.chapter_title, []).append(card)
    return list(chapters.items())


_CHAPTER_PREFIX_RE = re.compile(
    r"^(\d+\.\s*|chapter\s+\d+[.:\s]*|глава\s+\d+[.:\s]*)", re.IGNORECASE,
)


def _stable_id(text: str) -> int:
    """Generate a stable integer ID from a string."""
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16)


def _slugify(text: str) -> str:
    """Convert text to a tag-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\-]", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _strip_chapter_prefix(title: str) -> str:
    """Strip leading number/chapter prefixes like '1.', 'Chapter 3:', 'Глава 5.'."""
    return _CHAPTER_PREFIX_RE.sub("", title).strip() or title


def _slugify_for_filename(title: str) -> str:
    """Slugify a chapter title for filenames, stripping leading number prefixes."""
    slug = _slugify(_strip_chapter_prefix(title))
    if len(slug) > 180:
        slug = slug[:180].rstrip("-")
    return slug


def _build_chapter_deck(
    book_title: str, chapter_title: str, chapter_index: int, chapter_cards: list[Card],
) -> genanki.Deck:
    """Build a single subdeck for a chapter."""
    padded = str(chapter_index + 1).zfill(2)
    clean_title = _strip_chapter_prefix(chapter_title)
    subdeck_name = f"{book_title}::{padded} - {clean_title}"
    deck = genanki.Deck(deck_id=_stable_id(subdeck_name), name=subdeck_name)

    book_tag = f"book::{_slugify(book_title)}"

    for card in chapter_cards:
        q = _escape_field(card.question)
        a = _escape_field(card.answer)
        ex = _escape_field(card.example) if card.example else ""
        dg = _escape_field(card.image) if card.image else ""
        note = genanki.Note(
            model=CARD_MODEL,
            fields=[q, a, ex, dg, card.chapter_title, card.book_title],
            tags=[book_tag],
            guid=genanki.guid_for(card.question, card.book_title, card.chapter_title),
        )
        deck.add_note(note)

    return deck


def package_cards(
    cards: list[Card], book_title: str, output_path: str,
    media_files: list[str] | None = None,
) -> None:
    """Package all cards into a single .apkg file with chapter-based subdecks."""
    grouped = _group_cards_by_chapter(cards)
    decks = [
        _build_chapter_deck(book_title, chapter_title, i, chapter_cards)
        for i, (chapter_title, chapter_cards) in enumerate(grouped)
    ]
    package = genanki.Package(decks)
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def package_book_flat(
    cards: list[Card], book_title: str, output_path: str,
    media_files: list[str] | None = None,
) -> None:
    """Package book cards into a single flat deck (no subdecks), using CARD_MODEL."""
    deck = genanki.Deck(deck_id=_stable_id(book_title), name=book_title)
    tag = f"book::{_slugify(book_title)}"

    for card in cards:
        q = _escape_field(card.question)
        a = _escape_field(card.answer)
        ex = _escape_field(card.example) if card.example else ""
        dg = _escape_field(card.image) if card.image else ""
        note = genanki.Note(
            model=CARD_MODEL,
            fields=[q, a, ex, dg, card.chapter_title, card.book_title],
            tags=[tag],
            guid=genanki.guid_for(card.question, card.book_title, card.chapter_title),
        )
        deck.add_note(note)

    package = genanki.Package([deck])
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def package_cards_flat(
    cards: list[Card], deck_name: str, output_path: str,
    tag_prefix: str = "article", model: genanki.Model = ARTICLE_MODEL,
    media_files: list[str] | None = None,
) -> None:
    """Package all cards into a single flat deck (no subdecks)."""
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    tag = f"{tag_prefix}::{_slugify(deck_name)}"
    source_url = cards[0].source_url if cards else ""

    for card in cards:
        q = _escape_field(card.question)
        a = _escape_field(card.answer)
        ex = _escape_field(card.example) if card.example else ""
        dg = _escape_field(card.image) if card.image else ""
        note = genanki.Note(
            model=model,
            fields=[q, a, ex, dg, deck_name, source_url],
            tags=[tag],
            guid=genanki.guid_for(card.question, deck_name, source_url),
        )
        deck.add_note(note)

    package = genanki.Package([deck])
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def package_vocab_flat(
    cards: list[Card], deck_name: str, output_path: str,
    tag_name: str = "",
) -> None:
    """Package vocabulary cards into a single flat deck."""
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    tag = f"vocab::{_slugify(tag_name or deck_name)}"

    for card in cards:
        word = _escape_field(card.question)
        context = _escape_field(card.example) if card.example else ""
        translation = _escape_field(card.answer)
        definition = _escape_field(card.image) if card.image else ""
        example = _escape_field(card.source_url) if card.source_url else ""
        note = genanki.Note(
            model=VOCAB_MODEL,
            fields=[word, context, translation, definition, example,
                    card.book_title, card.chapter_title],
            tags=[tag],
            guid=genanki.guid_for(card.question, deck_name, "vocab"),
        )
        deck.add_note(note)

    package = genanki.Package([deck])
    package.write_to_file(output_path)


def chapter_filename(chapter_title: str, chapter_index: int) -> str:
    """Return the base filename (without extension) for a chapter."""
    padded = str(chapter_index + 1).zfill(2)
    return f"{padded} - {_slugify_for_filename(chapter_title)}"


def package_single_chapter(
    cards: list[Card], book_title: str, chapter_index: int, output_dir: str,
    media_files: list[str] | None = None,
) -> str:
    """Package a single chapter's cards and save to output_dir. Returns filepath."""
    os.makedirs(output_dir, exist_ok=True)
    chapter_title = cards[0].chapter_title
    deck = _build_chapter_deck(book_title, chapter_title, chapter_index, cards)
    base = chapter_filename(chapter_title, chapter_index)
    filepath = os.path.join(output_dir, f"{base}.apkg")
    package = genanki.Package([deck])
    if media_files:
        package.media_files = media_files
    package.write_to_file(filepath)
    return filepath


def _read_cards_from_apkg(filepath: str) -> list[Card]:
    """Read Card objects from an .apkg file (zip containing sqlite db)."""
    with zipfile.ZipFile(filepath, "r") as zf:
        db_name = None
        for name in zf.namelist():
            if name.startswith("collection.anki2"):
                db_name = name
                break
        if not db_name:
            return []

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(zf.read(db_name))
            tmp_path = tmp.name

    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute("SELECT flds FROM notes").fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)

    cards = []
    for (flds,) in rows:
        parts = flds.split("\x1f")
        if len(parts) >= 6:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                example=parts[2],
                image=parts[3],
                chapter_title=parts[4],
                book_title=parts[5],
            ))
        elif len(parts) >= 5:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                example=parts[2],
                chapter_title=parts[3],
                book_title=parts[4],
            ))
        elif len(parts) >= 4:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                chapter_title=parts[2],
                book_title=parts[3],
            ))
    return cards


def load_existing_chapters(chapters_dir: str) -> dict[int, list[Card]]:
    """Scan chapters dir for existing .apkg files. Returns {chapter_index: cards}."""
    result: dict[int, list[Card]] = {}
    if not os.path.isdir(chapters_dir):
        return result
    for name in sorted(os.listdir(chapters_dir)):
        if not name.endswith(".apkg"):
            continue
        try:
            index = int(name.split(" - ", 1)[0]) - 1  # padded "01" -> index 0
        except (ValueError, IndexError):
            continue
        apkg_path = os.path.join(chapters_dir, name)
        cards = _read_cards_from_apkg(apkg_path)
        if cards:
            result[index] = cards
    return result
