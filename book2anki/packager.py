import hashlib
import html
import os
import re
import sqlite3
import tempfile
import zipfile

import genanki

from book2anki.models import Card

_SAFE_TAGS = {"pre", "code", "/pre", "/code", "b", "/b", "i", "/i", "br", "br/",
              "ul", "/ul", "ol", "/ol", "li", "/li", "p", "/p"}
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
pre {
    background-color: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 8px 12px;
    overflow-x: auto;
    margin: 8px 0;
}
code {
    font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
    font-size: 16px;
}
"""

CARD_MODEL = genanki.Model(
    model_id=1607392319,
    name="book2anki Basic",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Chapter"},
        {"name": "Book"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>',
        },
    ],
    css=CARD_CSS,
)

ARTICLE_MODEL = genanki.Model(
    model_id=1607392320,
    name="book2anki Article",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Article"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>',
        },
    ],
    css=CARD_CSS,
)

YOUTUBE_MODEL = genanki.Model(
    model_id=1607392321,
    name="book2anki YouTube",
    fields=[
        {"name": "Question"},
        {"name": "Answer"},
        {"name": "Video"},
        {"name": "Source"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": '<div class="question">{{Question}}</div>',
            "afmt": '{{FrontSide}}<hr id="answer"><div class="answer">{{Answer}}</div>',
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
    r"^(\d+\.\s*|chapter\s+\d+[:\s]*|глава\s+\d+[.:\s]*)", re.IGNORECASE,
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
    book_title: str, chapter_title: str, chapter_index: int, chapter_cards: list[Card]
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
        note = genanki.Note(
            model=CARD_MODEL,
            fields=[q, a, card.chapter_title, card.book_title],
            tags=[book_tag],
            guid=genanki.guid_for(card.question, card.book_title, card.chapter_title),
        )
        deck.add_note(note)

    return deck


def package_cards(cards: list[Card], book_title: str, output_path: str) -> None:
    """Package all cards into a single .apkg file with chapter-based subdecks."""
    grouped = _group_cards_by_chapter(cards)
    decks = [
        _build_chapter_deck(book_title, chapter_title, i, chapter_cards)
        for i, (chapter_title, chapter_cards) in enumerate(grouped)
    ]
    package = genanki.Package(decks)
    package.write_to_file(output_path)


def package_cards_flat(
    cards: list[Card], deck_name: str, output_path: str,
    tag_prefix: str = "article", model: genanki.Model = ARTICLE_MODEL,
) -> None:
    """Package all cards into a single flat deck (no subdecks)."""
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    tag = f"{tag_prefix}::{_slugify(deck_name)}"
    source_url = cards[0].source_url if cards else ""

    for card in cards:
        q = _escape_field(card.question)
        a = _escape_field(card.answer)
        note = genanki.Note(
            model=model,
            fields=[q, a, deck_name, source_url],
            tags=[tag],
            guid=genanki.guid_for(card.question, deck_name, source_url),
        )
        deck.add_note(note)

    package = genanki.Package([deck])
    package.write_to_file(output_path)


def chapter_filename(chapter_title: str, chapter_index: int) -> str:
    """Return the base filename (without extension) for a chapter."""
    padded = str(chapter_index + 1).zfill(2)
    return f"{padded} - {_slugify_for_filename(chapter_title)}"


def package_single_chapter(
    cards: list[Card], book_title: str, chapter_index: int, output_dir: str
) -> str:
    """Package a single chapter's cards and save to output_dir. Returns filepath."""
    os.makedirs(output_dir, exist_ok=True)
    chapter_title = cards[0].chapter_title
    deck = _build_chapter_deck(book_title, chapter_title, chapter_index, cards)
    base = chapter_filename(chapter_title, chapter_index)
    filepath = os.path.join(output_dir, f"{base}.apkg")
    package = genanki.Package([deck])
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
        if len(parts) >= 4:
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
