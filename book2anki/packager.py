import hashlib
import html
import os
import re
import sqlite3
import tempfile
import zipfile

import genanki

from book2anki.models import Card, is_cloze, is_command, is_passive

_SAFE_TAGS = {"pre", "code", "/pre", "/code", "b", "/b", "br", "br/",
              "ul", "/ul", "ol", "/ol", "li", "/li", "p", "/p",
              "div", "/div",
              # The parsers carry the author's emphasis into the chapter text,
              # so a verbatim quote can bring <em> along; render it rather than
              # showing the reader an escaped tag.
              "em", "/em", "i", "/i",
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
:not(pre) > code {
    background-color: rgba(128, 128, 128, 0.12);
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 0.85em;
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

_CLOZE_CSS = """\
.cloze {
    font-weight: bold;
    color: #0b6ec4;
}
.card.night_mode .cloze {
    color: #6cb6ff;
}
.cloze-context {
    font-size: 15px;
    color: #888;
    margin-bottom: 10px;
}
.card.night_mode .cloze-context {
    color: #999;
}
.cloze-gloss {
    font-size: 17px;
    color: #666;
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px dashed rgba(128, 128, 128, 0.4);
}
.card.night_mode .cloze-gloss {
    color: #999;
}
"""

# Term cards: the sentence carries the deletion, so the "question" field is
# rendered through {{cloze:...}} on both sides. Fields deliberately mirror
# CARD_MODEL's layout and order so a deck containing both note types reads back
# through _read_cards_from_apkg unchanged, which is what resume relies on.
CLOZE_MODEL = genanki.Model(
    model_id=1607392326,
    name="book2anki Cloze",
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
            "name": "Cloze",
            "qfmt": '<div class="question">{{cloze:Question}}</div>',
            "afmt": (
                '<div class="question">{{cloze:Question}}</div>'
                '{{#Answer}}<div class="cloze-gloss">{{Answer}}</div>{{/Answer}}'
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
                '{{#Image}}<div class="image">{{Image}}</div>{{/Image}}'
            ),
        },
    ],
    css=CARD_CSS + _CLOZE_CSS,
    model_type=genanki.Model.CLOZE,
)


_COMMAND_CSS = """\
#typeans {
    font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
    font-size: 16px;
}
input#typeans {
    width: 100%;
    box-sizing: border-box;
    margin-top: 14px;
    padding: 6px 10px;
}
/* Anki's comparison of the typed line with the answer, drawn as our code block. */
code#typeans {
    display: block;
    background-color: rgba(128, 128, 128, 0.12);
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 4px;
    padding: 8px 12px;
    margin: 8px 0;
    white-space: pre-wrap;
}
"""

# Command cards: the reader types the line, and {{type:Answer}} shows their
# typing against the answer on the back. The back repeats {{Question}} rather
# than {{FrontSide}}, which would bring the input box along. Fields mirror
# CARD_MODEL's, like the cloze type's, so resume reads them back unchanged.
COMMAND_MODEL = genanki.Model(
    model_id=1607392328,
    name="book2anki Command",
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
            "qfmt": '<div class="question">{{Question}}</div>{{type:Answer}}',
            "afmt": (
                '<div class="question">{{Question}}</div><hr id="answer">{{type:Answer}}'
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
                '{{#Image}}<div class="image">{{Image}}</div>{{/Image}}'
            ),
        },
    ],
    css=CARD_CSS + _COMMAND_CSS,
)


def _note_model(card: Card, default: genanki.Model) -> genanki.Model:
    """Cloze and command cards have note types of their own; the rest use `default`."""
    if is_cloze(card):
        return CLOZE_MODEL
    if is_command(card):
        return COMMAND_MODEL
    return default


def _escaped_body(card: Card) -> list[str]:
    """The four rendered fields shared by every question/answer note type."""
    return [
        _escape_field(card.question),
        # A command is compared as typed, so even a tag-like "<b>" in it is text.
        html.escape(html.unescape(card.answer)) if is_command(card)
        else _escape_field(card.answer),
        _escape_field(card.example) if card.example else "",
        _escape_field(card.image) if card.image else "",
    ]


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

_VOCAB_CSS = """\
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
.register {
    font-size: 14px;
    font-weight: normal;
    color: #888;
    margin-top: 2px;
}
.card.night_mode .register {
    color: #777;
}
/* The register says why a word is only recognised, which is part of the
   answer: on the front it would be one more thing to read before recalling
   the meaning, and "archaic" or "technical" narrows the meaning down. It rides
   in the Word field, so the front can only hide it; only the answer side
   has the <hr id="answer">. */
.card:not(:has(#answer)) .register {
    display: none;
}
/* Our own play button, drawn like Anki's replay button but at the size of
   the IPA line and in its muted grey. Not Anki's class, whose stylesheet
   would blow the icon up to its own 40px. */
.card .play-button {
    display: inline-flex;
    text-decoration: none;
    margin: 0 0 0 2px;
    vertical-align: middle;
    cursor: pointer;
}
.card.night_mode .play-button svg circle {
    stroke: #666;
}
.card.night_mode .play-button svg path {
    fill: #999;
}
"""


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
    css=CARD_CSS + _VOCAB_CSS,
)

# Production / "speaking" vocab card: prompts in the reader's native language (plus
# the English definition as a sense cue) with the target word blanked out of the
# context sentence, so the learner has to actively recall and produce the English
# word/phrase. The etymology stays on the back so it doesn't give the word away.
VOCAB_PRODUCTION_MODEL = genanki.Model(
    model_id=1607392327,
    name="book2anki Vocab (Speaking)",
    fields=[
        {"name": "Word"},
        {"name": "ContextGap"},
        {"name": "Context"},
        {"name": "Translation"},
        {"name": "Definition"},
        {"name": "Etymology"},
        {"name": "Example"},
        {"name": "Book"},
        {"name": "Chapter"},
    ],
    templates=[
        {
            "name": "Card 1",
            "qfmt": (
                '<div class="translation">{{Translation}}</div>'
                '{{#Definition}}<div class="definition">{{Definition}}</div>{{/Definition}}'
                '{{#ContextGap}}<div class="context gap-context">{{ContextGap}}</div>{{/ContextGap}}'
            ),
            "afmt": (
                '{{FrontSide}}<hr id="answer">'
                '<div class="word">{{Word}}</div>'
                '{{#Context}}<div class="context">{{Context}}</div>{{/Context}}'
                '{{#Etymology}}<div class="etymology">{{Etymology}}</div>{{/Etymology}}'
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
            ),
        },
    ],
    css=CARD_CSS + _VOCAB_CSS + """\
.gap-context {
    margin-top: 14px;
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


def _model_tag(model_name: str) -> str:
    """Return an Anki-safe hierarchical tag for the generation model."""
    if not model_name.strip():
        return ""
    parts = re.split(r":+", model_name.strip().lower())
    clean_parts = []
    for part in parts:
        clean = re.sub(r"[^a-z0-9_.-]+", "-", part)
        clean = re.sub(r"-+", "-", clean).strip("-")
        if clean:
            clean_parts.append(clean)
    if not clean_parts:
        return ""
    return "model::" + "::".join(clean_parts)


def _note_tags(base_tag: str, card: Card, model_version: str = "") -> list[str]:
    """Build note tags, preserving model tags read from existing packages."""
    tags = [base_tag, *card.tags]
    if model_version and not any(tag.startswith("model::") for tag in tags):
        tags.append(_model_tag(model_version))
    return [tag for i, tag in enumerate(tags) if tag and tag not in tags[:i]]


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
    model_version: str = "",
) -> genanki.Deck:
    """Build a single subdeck for a chapter."""
    padded = str(chapter_index + 1).zfill(2)
    clean_title = _strip_chapter_prefix(chapter_title)
    subdeck_name = f"{book_title}::{padded} - {clean_title}"
    deck = genanki.Deck(deck_id=_stable_id(subdeck_name), name=subdeck_name)

    book_tag = f"book::{_slugify(book_title)}"

    for card in chapter_cards:
        note = genanki.Note(
            model=_note_model(card, CARD_MODEL),
            fields=[*_escaped_body(card), card.chapter_title, card.book_title],
            tags=_note_tags(book_tag, card, model_version),
            guid=genanki.guid_for(card.question, card.book_title, card.chapter_title),
        )
        deck.add_note(note)

    return deck


def _ordered_chapter_groups(
    cards: list[Card], chapter_order: dict[str, int] | None,
) -> list[tuple[str, int, list[Card]]]:
    """Group cards by chapter as (title, book index, cards), in book order.

    Without a chapter_order map, chapters fall back to being numbered by first
    appearance. Passing one keeps the combined deck's "01 - ", "02 - " prefixes
    aligned with the per-chapter files, which are named from the real index —
    otherwise `--chapters 5-7` writes `05 - …` files but `01 - …` subdecks.
    """
    grouped = _group_cards_by_chapter(cards)
    if chapter_order:
        grouped = sorted(
            grouped,
            key=lambda item: (chapter_order.get(item[0], len(chapter_order)), item[0]),
        )
    return [
        (title, chapter_order.get(title, i) if chapter_order else i, chapter_cards)
        for i, (title, chapter_cards) in enumerate(grouped)
    ]


def package_cards(
    cards: list[Card], book_title: str, output_path: str,
    media_files: list[str] | None = None,
    model_version: str = "",
    chapter_order: dict[str, int] | None = None,
) -> None:
    """Package all cards into a single .apkg file with chapter-based subdecks."""
    decks = [
        _build_chapter_deck(
            book_title, chapter_title, index, chapter_cards, model_version,
        )
        for chapter_title, index, chapter_cards
        in _ordered_chapter_groups(cards, chapter_order)
    ]
    package = genanki.Package(decks)
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def package_book_flat(
    cards: list[Card], book_title: str, output_path: str,
    media_files: list[str] | None = None,
    model_version: str = "",
) -> None:
    """Package book cards into a single flat deck (no subdecks), using CARD_MODEL."""
    deck = genanki.Deck(deck_id=_stable_id(book_title), name=book_title)
    tag = f"book::{_slugify(book_title)}"

    for card in cards:
        note = genanki.Note(
            model=_note_model(card, CARD_MODEL),
            fields=[*_escaped_body(card), card.chapter_title, card.book_title],
            tags=_note_tags(tag, card, model_version),
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
    model_version: str = "",
) -> None:
    """Package all cards into a single flat deck (no subdecks)."""
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    tag = f"{tag_prefix}::{_slugify(deck_name)}"
    source_url = cards[0].source_url if cards else ""

    for card in cards:
        note = genanki.Note(
            model=_note_model(card, model),
            fields=[*_escaped_body(card), deck_name, source_url],
            tags=_note_tags(tag, card, model_version),
            guid=genanki.guid_for(card.question, deck_name, source_url),
        )
        deck.add_note(note)

    package = genanki.Package([deck])
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def _practice_note(
    card: Card, deck_name: str, model_version: str = "",
) -> genanki.Note:
    """Build a genanki Note for a practice card."""
    q = _escape_field(card.question)
    a = _escape_field(card.answer)
    ex = _escape_field(card.example) if card.example else ""
    tag = f"practice::{_slugify(deck_name)}"
    return genanki.Note(
        model=CARD_MODEL,
        fields=[q, a, ex, "", card.chapter_title, card.book_title],
        tags=_note_tags(tag, card, model_version),
        guid=genanki.guid_for(card.question, deck_name, "practice"),
    )


def _practice_subdeck_name(deck_name: str, chapter_title: str, index: int) -> str:
    """Name a practice subdeck, numbered by the chapter's position in the book."""
    padded = str(index + 1).zfill(2)
    return f"{deck_name}::{padded} - {_strip_chapter_prefix(chapter_title)}"


def package_practice(
    cards: list[Card], deck_name: str, output_path: str, model_version: str = "",
    chapter_order: dict[str, int] | None = None,
) -> None:
    """Package all practice cards into a single .apkg with chapter subdecks."""
    decks = []
    for chapter_title, index, chapter_cards in _ordered_chapter_groups(
        cards, chapter_order,
    ):
        subdeck = _practice_subdeck_name(deck_name, chapter_title, index)
        deck = genanki.Deck(deck_id=_stable_id(subdeck), name=subdeck)
        for card in chapter_cards:
            deck.add_note(_practice_note(card, deck_name, model_version))
        decks.append(deck)
    package = genanki.Package(decks)
    package.write_to_file(output_path)


def package_practice_flat(
    cards: list[Card], deck_name: str, output_path: str, model_version: str = "",
) -> None:
    """Package practice cards into a single flat deck (no subdecks)."""
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    for card in cards:
        deck.add_note(_practice_note(card, deck_name, model_version))
    package = genanki.Package([deck])
    package.write_to_file(output_path)


def package_practice_chapter(
    cards: list[Card], deck_name: str, chapter_index: int, output_dir: str,
    model_version: str = "",
) -> str:
    """Save a single chapter's practice cards. Returns filepath."""
    os.makedirs(output_dir, exist_ok=True)
    chapter_title = cards[0].chapter_title
    subdeck = _practice_subdeck_name(deck_name, chapter_title, chapter_index)
    deck = genanki.Deck(deck_id=_stable_id(subdeck), name=subdeck)
    for card in cards:
        deck.add_note(_practice_note(card, deck_name, model_version))
    base = chapter_filename(chapter_title, chapter_index)
    filepath = os.path.join(output_dir, f"{base}.apkg")
    package = genanki.Package([deck])
    package.write_to_file(filepath)
    return filepath


_BOLD_RE = re.compile(r"<b>.*?</b>", re.IGNORECASE | re.DOTALL)


def _gap_context(context: str) -> str:
    """Blank out the bolded target word/phrase in a context sentence.

    The vocab prompt wraps the target word in <b>…</b>; we replace it with an
    underlined gap so the learner must produce the word. Returns "" when the
    sentence has no highlighted word to blank (front then shows translation only).
    """
    if not context or not _BOLD_RE.search(context):
        return ""
    return _BOLD_RE.sub("<b>_____</b>", context)


_ETYM_RE = re.compile(r'<div class="etymology">(.*?)</div>', re.IGNORECASE | re.DOTALL)


def _split_etymology(definition: str) -> tuple[str, str]:
    """Split a bundled Definition field into (definition, etymology) text.

    The generator stores etymology as a `<div class="etymology">…</div>` appended
    to the definition. Production cards show the definition on the front and the
    etymology on the back, so they need to be separated. Returns the etymology's
    inner text (no wrapper); the template re-wraps it.
    """
    if not definition:
        return "", ""
    match = _ETYM_RE.search(definition)
    if not match:
        return definition, ""
    rest = (definition[:match.start()] + definition[match.end():]).strip()
    return rest, match.group(1).strip()


def _vocab_word_field(card: Card) -> str:
    """The word, with its pronunciation clip when there is one.

    The clip rides in the Word field, which the recognition card shows on the
    front and the production card reveals on the back, rather than in a field
    of its own: a new field would change both note types, which Anki can't
    merge into the decks people have already imported. The guid is taken from
    `card.question`, so adding audio later doesn't duplicate a word.

    The button sits at the end of the IPA line, where the eye already is when
    it wants the pronunciation. It must stay after the first <div>: the
    existing-Anki dedup reads the word as everything before it.
    """
    word = _escape_field(card.question)
    if not card.audio:
        return word
    ipa = re.search(r'<div class="ipa">.*?(?=</div>)', word, re.DOTALL)
    if ipa:
        return word[:ipa.end()] + " " + _play_button(card.audio) + word[ipa.end():]
    return word + f'<div class="ipa">{_play_button(card.audio)}</div>'


# Anki's own replay-button icon.
# Sized and coloured by attributes, not the card CSS: Anki's editor shows the
# field without that CSS, where a bare SVG fills the field in black.
_PLAY_ICON = (
    '<svg viewBox="0 0 64 64" width="18" height="18">'
    '<circle cx="32" cy="32" r="29" fill="none" stroke="#aaa" stroke-width="3"/>'
    '<path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z" fill="#888"/>'
    '</svg>'
)


def _play_button(filename: str) -> str:
    """A button that plays the clip only when clicked.

    A [sound:] tag would play by itself as the card appears, unless the
    reader's deck options turn that off, which a deck file can't do for them.
    Anki counts an <audio src> as a use of the file, so it syncs, and Check
    Media keeps it.
    """
    src = html.escape(filename)
    return (
        f'<span class="audio"><a class="play-button" href="#" '
        f'onclick="var a=this.nextElementSibling;a.currentTime=0;a.play();return false;">'
        f'{_PLAY_ICON}</a><audio src="{src}" preload="none"></audio></span>'
    )


def _vocab_recognition_note(
    card: Card, deck_name: str, tag: str, model_version: str,
) -> genanki.Note:
    """A recognition card: the word in its context → what it means."""
    word = _vocab_word_field(card)
    context = _escape_field(card.example) if card.example else ""
    translation = _escape_field(card.answer)
    definition = _escape_field(card.image) if card.image else ""
    example = _escape_field(card.source_url) if card.source_url else ""
    return genanki.Note(
        model=VOCAB_MODEL,
        fields=[word, context, translation, definition, example,
                card.book_title, card.chapter_title],
        tags=_note_tags(tag, card, model_version),
        guid=genanki.guid_for(card.question, deck_name, "vocab"),
    )


def _vocab_production_note(
    card: Card, deck_name: str, tag: str, model_version: str,
) -> genanki.Note:
    """A production ("speaking") card: the meaning in the reader's language,
    with the word gapped out of its context → produce the word.
    """
    word = _vocab_word_field(card)
    context = _escape_field(card.example) if card.example else ""
    context_gap = _escape_field(_gap_context(card.example)) if card.example else ""
    translation = _escape_field(card.answer)
    def_text, etym_text = _split_etymology(card.image)
    definition = _escape_field(def_text) if def_text else ""
    etymology = _escape_field(etym_text) if etym_text else ""
    example = _escape_field(card.source_url) if card.source_url else ""
    return genanki.Note(
        model=VOCAB_PRODUCTION_MODEL,
        fields=[word, context_gap, context, translation, definition,
                etymology, example, card.book_title, card.chapter_title],
        tags=_note_tags(tag, card, model_version),
        guid=genanki.guid_for(card.question, deck_name, "vocab-speak"),
    )


def package_vocab(
    cards: list[Card], deck_name: str, output_path: str, mode: str = "auto",
    tag_name: str = "", model_version: str = "",
    media_files: list[str] | None = None,
) -> None:
    """Package vocabulary cards into a single flat deck.

    `mode` picks the card direction: "production" and "recognition" force one
    direction for every word; "auto" asks a word the reader would use
    themselves for production, and one they only need to understand on the
    page (`is_passive`) for recognition. Both note types share the "vocab::"
    tag prefix and put the word first, so the existing-Anki dedup
    (read_vocab_words) finds a word whichever way it was learned.
    """
    deck = genanki.Deck(deck_id=_stable_id(deck_name), name=deck_name)
    tag = f"vocab::{_slugify(tag_name or deck_name)}"

    for card in cards:
        recognise = mode == "recognition" or (mode == "auto" and is_passive(card))
        build = _vocab_recognition_note if recognise else _vocab_production_note
        deck.add_note(build(card, deck_name, tag, model_version))

    package = genanki.Package([deck])
    if media_files:
        package.media_files = media_files
    package.write_to_file(output_path)


def chapter_filename(chapter_title: str, chapter_index: int) -> str:
    """Return the base filename (without extension) for a chapter."""
    padded = str(chapter_index + 1).zfill(2)
    return f"{padded} - {_slugify_for_filename(chapter_title)}"


def package_single_chapter(
    cards: list[Card], book_title: str, chapter_index: int, output_dir: str,
    media_files: list[str] | None = None,
    model_version: str = "",
) -> str:
    """Package a single chapter's cards and save to output_dir. Returns filepath."""
    os.makedirs(output_dir, exist_ok=True)
    chapter_title = cards[0].chapter_title
    deck = _build_chapter_deck(
        book_title, chapter_title, chapter_index, cards, model_version,
    )
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
        rows = conn.execute("SELECT flds, tags FROM notes").fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)

    cards = []
    for flds, raw_tags in rows:
        parts = flds.split("\x1f")
        tags = raw_tags.strip().split() if raw_tags else []
        if len(parts) >= 6:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                example=parts[2],
                image=parts[3],
                chapter_title=parts[4],
                book_title=parts[5],
                tags=tags,
            ))
        elif len(parts) >= 5:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                example=parts[2],
                chapter_title=parts[3],
                book_title=parts[4],
                tags=tags,
            ))
        elif len(parts) >= 4:
            cards.append(Card(
                question=parts[0],
                answer=parts[1],
                chapter_title=parts[2],
                book_title=parts[3],
                tags=tags,
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
