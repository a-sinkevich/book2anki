import email.message
import importlib
import urllib.error

import openai
import pytest

from book2anki import audio
from book2anki.audio import (
    AudioError,
    attach_audio,
    card_ipa,
    headword,
    openai_mp3,
    pick_recordings,
    tts_instructions,
)
from book2anki.models import Card

# The errors these tests raise carry the SDK's own request and response
# objects, and openai 3 moved from httpx to its successor, httpx2.
httpx = importlib.import_module("httpx2" if int(openai.__version__.split(".")[0]) >= 3 else "httpx")

SUSURRUS = """\
==English==
===Etymology===
Borrowed from Latin.

===Pronunciation===
* {{IPA|en|/ˈsuː.sə.ɹəs/|a=UK}}
** {{audio|en|LL-Q1860 (eng)-Vealhurl-susurrus.wav|a=Southern England}}
* {{IPA|en|/ˈsu.sə.ɹəs/|a=US}}
** {{audio|en|En-us-susurrus.ogg|a=US}}

===Noun===
{{en-noun}}

==Latin==
===Pronunciation===
* {{audio|la|La-susurrus.ogg}}
"""

LEAD = """\
==English==
===Etymology 1===
====Pronunciation====
* {{audio|en|En-us-lead-metal.oga|a=US}}
===Etymology 2===
====Pronunciation====
* {{audio|en|En-us-lead-guide.oga|a=US}}
"""

RECORD = """\
==English==
===Pronunciation===
* {{q|noun}} {{IPA|en|/ˈɹɛk.ɚd/}}
* {{audio|en|en-us-record-noun.ogg|a=US}}
* {{q|verb}} {{IPA|en|/ɹɪˈkɔɹd/}}
* {{audio|en|en-us-record-verb.ogg|a=US|pos=verb}}
"""


class TestWordField:
    def test_headword_drops_ipa_labels_and_the_infinitive_marker(self):
        q = 'to come to grips with<div class="ipa">/kʌm/</div><div class="register">informal</div>'
        assert headword(q, "en") == "come to grips with"

    def test_headword_keeps_case_and_to_in_other_languages(self):
        assert headword('Hund<div class="ipa">/hʊnt/</div>', "de") == "Hund"
        assert headword("to", "de") == "to"

    def test_card_ipa(self):
        assert card_ipa('susurrus<div class="ipa">/sjuːˈsʌrəs/</div>') == "/sjuːˈsʌrəs/"
        assert card_ipa("susurrus") == ""


class TestPickRecordings:
    def test_prefers_british_recordings_for_english(self):
        assert pick_recordings(SUSURRUS, "English", "en") == [
            "LL-Q1860 (eng)-Vealhurl-susurrus.wav", "En-us-susurrus.ogg",
        ]

    def test_reads_only_the_sources_language_section(self):
        assert pick_recordings(SUSURRUS, "Latin", "la") == ["La-susurrus.ogg"]
        assert pick_recordings(SUSURRUS, "German", "de") == []

    def test_skips_homographs_with_separate_pronunciations(self):
        assert pick_recordings(LEAD, "English", "en") == []

    def test_skips_a_pronunciation_split_by_part_of_speech(self):
        assert pick_recordings(RECORD, "English", "en") == []


def test_instructions_carry_the_books_sentence_without_its_markup():
    text = tts_instructions("en", "Please <b>record</b> the meeting &amp; notes.")
    assert "British accent" in text
    assert '"Please record the meeting & notes."' in text
    assert "sentence" not in tts_instructions("en", "")
    assert "standard German accent" in tts_instructions("de", "")


class _FakeSpeech:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return type("Response", (), {"content": self.outcome})()


class _FakeClient:
    def __init__(self, outcome) -> None:
        self.audio = type("Audio", (), {})()
        self.audio.speech = _FakeSpeech(outcome)


def _openai_error(cls, status: int, code: str | None = None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    body = {"code": code, "message": "nope"} if code else None  # the SDK passes the inner "error"
    return cls("nope", response=response, body=body)


class TestOpenAiSpeech:
    def test_asks_for_an_mp3_of_the_word(self, monkeypatch):
        monkeypatch.delenv("OPENAI_TTS_VOICE", raising=False)
        client = _FakeClient(b"mp3")
        assert openai_mp3(client, "susurrus", "say it") == b"mp3"
        kwargs = client.audio.speech.kwargs
        assert kwargs["input"] == "susurrus"
        assert kwargs["instructions"] == "say it"
        assert kwargs["response_format"] == "mp3"
        assert kwargs["voice"] == "marin"

    def test_a_bad_key_is_fatal(self):
        client = _FakeClient(_openai_error(openai.AuthenticationError, 401))
        with pytest.raises(AudioError, match="OPENAI_API_KEY"):
            openai_mp3(client, "word", "")

    def test_an_empty_account_is_fatal(self):
        client = _FakeClient(_openai_error(openai.RateLimitError, 429, "insufficient_quota"))
        with pytest.raises(AudioError, match="out of credit"):
            openai_mp3(client, "word", "")

    def test_a_plain_rate_limit_is_not_fatal(self):
        client = _FakeClient(_openai_error(openai.RateLimitError, 429, "rate_limit_exceeded"))
        with pytest.raises(openai.RateLimitError):
            openai_mp3(client, "word", "")


def _vocab(word: str) -> Card:
    return Card(question=f'{word}<div class="ipa">/{word}/</div>', answer="x",
                chapter_title="c", book_title="b")


class TestAttachAudio:
    @pytest.fixture(autouse=True)
    def openai_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")

    def test_every_word_is_spoken_by_openai_in_the_books_sense(self, monkeypatch, tmp_path):
        def fail(*_args):
            raise AssertionError("asked Wiktionary although OpenAI answered")
        monkeypatch.setattr(audio, "wiktionary_mp3", fail)
        calls = []

        def speak(client, text, instructions):
            calls.append((text, instructions))
            return b"tts"
        monkeypatch.setattr(audio, "openai_mp3", speak)

        cards = [_vocab("susurrus"), _vocab("record"), _vocab("to mull over")]
        cards[1].example = "Please <b>record</b> the meeting."
        logged: list[str] = []
        media = attach_audio(cards, "en", log=logged.append, cache_dir=tmp_path)

        assert sorted(text for text, _ in calls) == ["mull over", "record", "susurrus"]
        assert any('"Please record the meeting."' in i for _, i in calls)
        assert [open(p, "rb").read() for p in media] == [b"tts"] * 3
        assert all(c.audio for c in cards)
        assert logged == ["Audio: 3 openai"]

    def test_a_word_openai_fails_on_falls_back_to_a_recording(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audio, "wiktionary_mp3", lambda word, lang: b"real")

        def speak(client, text, instructions):
            if text == "susurrus":
                raise openai.APIConnectionError(request=httpx.Request("POST", "https://x"))
            return b"tts"
        monkeypatch.setattr(audio, "openai_mp3", speak)

        cards = [_vocab("susurrus"), _vocab("record")]
        logged: list[str] = []
        media = attach_audio(cards, "en", log=logged.append, cache_dir=tmp_path)
        assert [open(p, "rb").read() for p in media] == [b"real", b"tts"]
        assert logged == ["Audio: 1 openai, 1 wiktionary"]

    def test_cached_clips_are_not_fetched_again(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audio, "openai_mp3", lambda *_args: b"tts")
        attach_audio([_vocab("susurrus")], "en", log=lambda _: None, cache_dir=tmp_path)

        def fail(*_args):
            raise AssertionError("fetched a cached word")
        monkeypatch.setattr(audio, "openai_mp3", fail)
        monkeypatch.setattr(audio, "wiktionary_mp3", fail)
        logged: list[str] = []
        card = _vocab("susurrus")
        attach_audio([card], "en", log=logged.append, cache_dir=tmp_path)
        assert card.audio and logged == ["Audio: 1 cached"]

    def test_another_voice_or_source_makes_a_new_clip(self, monkeypatch):
        names = {audio._cache_name("wiktionary", "gist", "/dʒɪst/", "en")}
        monkeypatch.delenv("OPENAI_TTS_VOICE", raising=False)
        names.add(audio._cache_name("openai", "gist", "/dʒɪst/", "en"))
        monkeypatch.setenv("OPENAI_TTS_VOICE", "sage")
        names.add(audio._cache_name("openai", "gist", "/dʒɪst/", "en"))
        assert len(names) == 3

    def test_without_a_key_a_word_gets_its_recording(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.setattr(audio, "wiktionary_mp3", lambda word, lang: b"real")
        card = _vocab("susurrus")
        logged: list[str] = []
        media = attach_audio([card], "en", log=logged.append, cache_dir=tmp_path)
        assert [open(p, "rb").read() for p in media] == [b"real"]
        assert logged == ["Audio: 1 wiktionary"]

    def test_without_a_key_words_go_silent_and_the_log_says_how_to_fix_it(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.setattr(audio, "wiktionary_mp3", lambda word, lang: None)
        card = _vocab("betwixt")
        logged: list[str] = []
        assert attach_audio([card], "en", log=logged.append, cache_dir=tmp_path) == []
        assert card.audio == ""
        assert "OPENAI_API_KEY" in logged[1]

    def test_a_fatal_error_stops_further_speech_requests(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audio, "wiktionary_mp3", lambda word, lang: None)
        calls = []

        def speak(*args):
            calls.append(args)
            raise AudioError("OpenAI says the account is out of credit")
        monkeypatch.setattr(audio, "openai_mp3", speak)
        logged: list[str] = []
        cards = [_vocab(w) for w in ("a", "b", "c", "d", "e", "f", "g", "h")]
        attach_audio(cards, "en", log=logged.append, cache_dir=tmp_path)
        assert len(calls) <= 4    # only the requests already in flight
        assert "out of credit" in logged[1]

    def test_a_network_failure_leaves_the_word_without_audio(self, monkeypatch, tmp_path):
        def down(word, lang):
            raise OSError("no network")
        monkeypatch.setattr(audio, "wiktionary_mp3", down)

        def speak(*_args):
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://x"))
        monkeypatch.setattr(audio, "openai_mp3", speak)
        card = _vocab("betwixt")
        assert attach_audio([card], "en", log=lambda _: None, cache_dir=tmp_path) == []
        assert card.audio == ""


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args) -> None:
        pass


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x", code, "err", headers, None)


class TestRateLimits:
    def _serve(self, monkeypatch, outcomes):
        """Make urlopen return/raise `outcomes` in turn; return the sleeps taken."""
        outcomes = list(outcomes)

        def urlopen(*_args, **_kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return _Response(outcome)
        sleeps: list[float] = []
        monkeypatch.setattr(audio.urllib.request, "urlopen", urlopen)
        monkeypatch.setattr(audio.time, "sleep", sleeps.append)
        return sleeps

    def test_waits_as_long_as_the_server_asks_then_retries(self, monkeypatch):
        sleeps = self._serve(monkeypatch, [_http_error(429, "11"), b"mp3"])
        assert audio._get("https://x") == b"mp3"
        assert sleeps == [11.0]

    def test_backs_off_when_the_server_gives_no_delay(self, monkeypatch):
        sleeps = self._serve(monkeypatch, [_http_error(503), _http_error(429), b"mp3"])
        assert audio._get("https://x") == b"mp3"
        assert sleeps == [2.0, 4.0]

    def test_gives_up_after_the_last_attempt(self, monkeypatch):
        self._serve(monkeypatch, [_http_error(429, "1")] * audio._ATTEMPTS)
        with pytest.raises(urllib.error.HTTPError):
            audio._get("https://x")

    def test_other_errors_are_not_retried(self, monkeypatch):
        sleeps = self._serve(monkeypatch, [_http_error(404)])
        with pytest.raises(urllib.error.HTTPError):
            audio._get("https://x")
        assert sleeps == []
