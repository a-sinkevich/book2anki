"""Pronunciation audio for vocab cards.

With an OpenAI key every word is synthesised by OpenAI's speech model, so the
whole deck is one voice. It knows how rare words are said rather than guessing
from spelling, and is shown the book's sentence so a homograph comes out as the
book meant it. Without a key, or when OpenAI fails, a word gets a real
speaker's recording from Wiktionary if there is one that unambiguously belongs
to it. Clips are cached on disk, so re-running a book doesn't fetch them again.
"""

import hashlib
import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import openai

from book2anki.models import Card

_USER_AGENT = "book2anki (https://github.com/a-sinkevich/book2anki)"
_CACHE_DIR = Path.home() / ".cache" / "book2anki" / "audio"

# The heading of each source language's section on English Wiktionary.
_LANGUAGES: dict[str, str] = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "sv": "Swedish", "no": "Norwegian Bokmål", "ru": "Russian",
    "uk": "Ukrainian", "tr": "Turkish", "ja": "Japanese", "zh": "Chinese",
    "ko": "Korean",
}

# English is heard in one accent: recordings are picked, and speech asked
# for, in it. Part of the cache key, so changing it refetches every clip.
_ENGLISH_ACCENT = "British"

_TTS_MODEL = "gpt-4o-mini-tts"
_TTS_VOICE = "marin"

_AUDIO_TEMPLATE_RE = re.compile(r"\{\{audio\|([^|}]+)\|([^|}]+)((?:\|[^}]*)?)\}\}")
_HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*=+\s*$", re.MULTILINE)
# A pronunciation section that splits by part of speech ("record": noun
# /ˈɹɛk.ɚd/, verb /ɹɪˈkɔɹd/) can't tell us which recording is our word.
_SPLIT_BY_POS_RE = re.compile(r"\b(?:noun|verb|adjective|adverb)\b|pos=", re.IGNORECASE)


class AudioError(Exception):
    """A failure that makes every further request pointless (e.g. a bad key)."""


def headword(question: str, lang: str) -> str:
    """The word as it would be looked up: case kept, IPA and labels dropped."""
    word = html.unescape(re.split(r"<\w", question, maxsplit=1)[0]).split("\n")[0].strip()
    if lang == "en" and word.lower().startswith("to "):
        word = word[3:].strip()
    return word


def card_ipa(question: str) -> str:
    """The IPA the vocab prompt put into the word field, if any."""
    m = re.search(r'<div class="ipa">(.*?)</div>', question, re.DOTALL)
    return html.unescape(m.group(1)).strip() if m else ""


# --- Wiktionary ---

def _language_section(wikitext: str, lang_name: str) -> str:
    m = re.search(rf"^==\s*{re.escape(lang_name)}\s*==\s*$", wikitext, re.MULTILINE)
    if not m:
        return ""
    end = re.search(r"^==[^=]", wikitext[m.end():], re.MULTILINE)
    return wikitext[m.end():m.end() + end.start()] if end else wikitext[m.end():]


def _accent_rank(filename: str, params: str) -> int:
    """Prefer British recordings for English, to match the synthesised accent."""
    if re.search(r"\b(?:UK|RP|England|English)\b", params) or filename.lower().startswith("en-uk-"):
        return 0
    if re.search(r"\b(?:US|GA|General American)\b", params) or filename.lower().startswith("en-us-"):
        return 1
    return 2


def pick_recordings(wikitext: str, lang_name: str, lang: str) -> list[str]:
    """Recording file names on a Wiktionary page for the word, best first.

    Empty when the page has none for the language, or when the language has
    more than one pronunciation (homographs like "lead" the metal and "to
    lead"), since nothing on the page says which of them the book meant.
    """
    section = _language_section(wikitext, lang_name)
    headings = [m for m in _HEADING_RE.finditer(section)
                if re.fullmatch(r"Pronunciation(?:\s*\d+)?", m.group(2))]
    if len(headings) != 1:
        return []
    start = headings[0].end()
    following = _HEADING_RE.search(section, start)
    pronunciation = section[start:following.start() if following else len(section)]
    if _SPLIT_BY_POS_RE.search(pronunciation):
        return []
    files = [(m.group(2).strip(), m.group(3)) for m in _AUDIO_TEMPLATE_RE.finditer(pronunciation)
             if m.group(1).strip() == lang]
    if lang == "en":
        files.sort(key=lambda f: _accent_rank(*f))
    return [name for name, _ in files]


def _commons_title(name: str) -> str:
    """A file name as Commons spells its title: spaces, first letter capital."""
    name = name.replace("_", " ").strip()
    return name[:1].upper() + name[1:]


def _mp3_urls(files: list[str]) -> dict[str, str]:
    """Commons mp3 URL for each recording (every client plays mp3, not all ogg)."""
    query = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "videoinfo", "viprop": "url|mime|derivatives",
        "titles": "|".join(f"File:{f}" for f in files),
    })
    data = json.loads(_get(f"https://commons.wikimedia.org/w/api.php?{query}"))
    urls: dict[str, str] = {}
    for page in data.get("query", {}).get("pages", []):
        for info in page.get("videoinfo", [])[:1]:
            name = _commons_title(page["title"].removeprefix("File:"))
            if info.get("mime") == "audio/mpeg":
                urls[name] = info["url"]
                continue
            for d in info.get("derivatives", []):
                if d.get("type", "").startswith("audio/mpeg"):
                    urls[name] = d["src"]
                    break
    return urls


def wiktionary_mp3(word: str, lang: str) -> bytes | None:
    """A real speaker saying the word, from Wiktionary, if it has one."""
    lang_name = _LANGUAGES.get(lang, "")
    if not lang_name:
        return None
    query = urllib.parse.urlencode({
        "action": "parse", "format": "json", "formatversion": "2",
        "prop": "wikitext", "redirects": "1", "page": word,
    })
    data = json.loads(_get(f"https://en.wiktionary.org/w/api.php?{query}"))
    wikitext = data.get("parse", {}).get("wikitext", "")
    files = pick_recordings(wikitext, lang_name, lang)
    if not files:
        return None
    urls = _mp3_urls(files)
    for f in files:
        url = urls.get(_commons_title(f))
        if url:
            return _get(url)
    return None


# --- OpenAI ---

def tts_instructions(lang: str, context: str) -> str:
    """How the speech model should say a headword.

    The sentence is what tells "to record" from "a record"; the speech model
    reads instructions for delivery, so it isn't spoken.
    """
    lang_name = _LANGUAGES.get(lang, lang)
    accent = ("a standard British accent (Received Pronunciation)" if lang == "en"
              else f"a standard {lang_name} accent")
    text = (f"You are pronouncing a {lang_name} dictionary headword for a "
            f"language learner. Say it once, clearly and at a natural pace, "
            f"with {accent}, the way a dictionary recording would.")
    context = html.unescape(re.sub(r"<[^>]+>", "", context)).strip()
    if context:
        text += (f' It is used as in this sentence, so pronounce it the way it '
                 f'is meant there: "{context}"')
    return text


def _tts_model() -> str:
    return os.environ.get("OPENAI_TTS_MODEL") or _TTS_MODEL


def _tts_voice() -> str:
    return os.environ.get("OPENAI_TTS_VOICE") or _TTS_VOICE


def openai_mp3(client: openai.OpenAI, text: str, instructions: str) -> bytes:
    """Synthesise `text` with OpenAI's speech model."""
    try:
        response = client.audio.speech.create(
            model=_tts_model(),
            voice=_tts_voice(),
            input=text,
            instructions=instructions,
            response_format="mp3",
        )
    except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
        raise AudioError(
            f"OpenAI refused the request (HTTP {e.status_code}): check OPENAI_API_KEY") from e
    except openai.RateLimitError as e:
        if e.code == "insufficient_quota":
            raise AudioError(
                "OpenAI says the account is out of credit: add some at "
                "https://platform.openai.com/settings/organization/billing") from e
        raise
    clip: bytes = response.content
    return clip


# --- Orchestration ---

def _ssl_context() -> ssl.SSLContext:
    # The frozen binary may not see the system CA store; certifi ships with
    # the API client libraries, so prefer its bundle when it is there.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_ATTEMPTS = 5
_MAX_WAIT = 60


def _retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    """How long the server asked us to wait, or a growing backoff if it didn't say."""
    try:
        return min(float(error.headers.get("Retry-After", "")), _MAX_WAIT)
    except ValueError:
        return min(2.0 ** (attempt + 1), _MAX_WAIT)


def _get(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    """Fetch a URL, waiting out rate limits.

    Wikimedia's file server answers a burst of downloads with 429 after a
    dozen or so, and says how long to wait. Giving up instead would leave
    every later word silent.
    """
    req = urllib.request.Request(url, data=data, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    for attempt in range(_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
                body: bytes = resp.read()
                return body
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == _ATTEMPTS - 1:
                raise
            time.sleep(_retry_delay(e, attempt))
    raise AssertionError("unreachable")


def _cache_name(source: str, word: str, ipa: str, lang: str) -> str:
    """A clip's file name; another source, voice or accent makes a new clip."""
    speaker = f"{_tts_model()}\0{_tts_voice()}" if source == "openai" else source
    key = f"{speaker}\0{_ENGLISH_ACCENT}\0{lang}\0{word}\0{ipa}"
    return f"book2anki-{hashlib.sha1(key.encode()).hexdigest()[:16]}.mp3"


def attach_audio(
    cards: list[Card], lang: str, log: Callable[[str], None] = print,
    cache_dir: Path = _CACHE_DIR,
) -> list[str]:
    """Give each vocab card a pronunciation clip; return the media file paths.

    Sets `card.audio` to the clip's file name. With OPENAI_API_KEY set every
    word is synthesised, falling back to a Wiktionary recording when OpenAI
    fails; without it, words Wiktionary has no recording of go without audio.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("OPENAI_API_KEY", "")
    # The SDK waits out rate limits itself, as long as it is allowed to retry.
    client = openai.OpenAI(api_key=key, max_retries=5, timeout=60.0) if key else None
    fatal: list[str] = []
    counts = {"cached": 0, "openai": 0, "wiktionary": 0, "missing": 0}
    sources = ["openai", "wiktionary"] if client else ["wiktionary"]

    def download(source: str, word: str, card: Card) -> bytes | None:
        try:
            if source == "wiktionary":
                return wiktionary_mp3(word, lang)
            if client is not None and not fatal:
                return openai_mp3(client, word, tts_instructions(lang, card.example))
        except AudioError as e:
            fatal.append(str(e))
        except (OSError, ValueError, KeyError, openai.OpenAIError):
            pass
        return None

    def fetch(card: Card) -> tuple[str, str]:
        """(source, path) for one card; source is a key of `counts`."""
        word = headword(card.question, lang)
        ipa = card_ipa(card.question)
        for source in sources:
            path = cache_dir / _cache_name(source, word, ipa, lang)
            if path.is_file():
                return "cached", str(path)
            clip = download(source, word, card)
            if clip:
                path.write_bytes(clip)
                return source, str(path)
        return "missing", ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, cards))

    media: list[str] = []
    for card, (source, path) in zip(cards, results):
        counts[source] += 1
        if path:
            card.audio = os.path.basename(path)
            if path not in media:
                media.append(path)

    parts = [f"{n} {name}" for name, n in counts.items() if n]
    log(f"Audio: {', '.join(parts)}")
    if fatal:
        log(f"  {fatal[0]}")
    elif counts["missing"] and client is None:
        log("  Set OPENAI_API_KEY in ~/.book2anki.env to synthesise words"
            " Wiktionary has no recording of.")
    return media
