from unittest.mock import patch

import pytest

from book2anki.parser_youtube import is_youtube_input, _extract_video_id, parse_youtube


class TestIsYoutubeInput:
    def test_watch_url(self):
        assert is_youtube_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_short_url(self):
        assert is_youtube_input("https://youtu.be/dQw4w9WgXcQ")

    def test_watch_with_extras(self):
        assert is_youtube_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42")

    def test_bare_video_id(self):
        assert is_youtube_input("dQw4w9WgXcQ")

    def test_bare_id_with_dash(self):
        assert is_youtube_input("lrSB9gEUJEQ")

    def test_not_youtube(self):
        assert not is_youtube_input("https://example.com/article")

    def test_not_youtube_similar(self):
        assert not is_youtube_input("https://notyoutube.com/watch?v=abc")

    def test_too_short_for_id(self):
        assert not is_youtube_input("abc")

    def test_too_long_for_id(self):
        assert not is_youtube_input("abcdefghijkl")

    def test_epub_not_matched(self):
        assert not is_youtube_input("mybook.epub")


class TestExtractVideoId:
    def test_watch_url(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_with_query_params(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120") == "dQw4w9WgXcQ"

    def test_bare_video_id(self):
        assert _extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        with pytest.raises(ValueError, match="Cannot extract video ID"):
            _extract_video_id("https://example.com/page")


class TestParseYoutube:
    @patch("book2anki.parser_youtube._fetch_title")
    @patch("book2anki.parser_youtube._fetch_transcript")
    def test_returns_chapter(self, mock_transcript, mock_title):
        mock_title.return_value = "Test Video"
        mock_transcript.return_value = "Hello world\nThis is a test"

        title, chapters = parse_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert title == "Test Video"
        assert len(chapters) == 1
        assert chapters[0].title == "Test Video"
        assert chapters[0].text == "Hello world\nThis is a test"
        assert chapters[0].index == 0

    @patch("book2anki.parser_youtube._fetch_title")
    @patch("book2anki.parser_youtube._fetch_transcript")
    def test_bare_id(self, mock_transcript, mock_title):
        mock_title.return_value = "Test Video"
        mock_transcript.return_value = "Some transcript text"

        title, chapters = parse_youtube("dQw4w9WgXcQ")

        assert title == "Test Video"
        assert len(chapters) == 1
        mock_transcript.assert_called_with("dQw4w9WgXcQ")

    @patch("book2anki.parser_youtube._fetch_title")
    @patch("book2anki.parser_youtube._fetch_transcript")
    def test_empty_transcript_raises(self, mock_transcript, mock_title):
        mock_title.return_value = "Test Video"
        mock_transcript.return_value = ""

        with pytest.raises(ValueError, match="No transcript available"):
            parse_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
