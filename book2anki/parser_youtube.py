import html
import re
import ssl
import urllib.request
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi

from book2anki.models import Chapter


_YOUTUBE_URL_RE = re.compile(r"(?:youtube\.com/watch\?.*v=|youtu\.be/)([\w-]{11})")
_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")


def is_youtube_input(text: str) -> bool:
    """Check if input is a YouTube URL or a bare video ID."""
    return bool(_YOUTUBE_URL_RE.search(text) or _VIDEO_ID_RE.match(text))


def parse_youtube(source: str) -> tuple[str, list[Chapter]]:
    """Fetch YouTube transcript and return (video_title, [chapter])."""
    video_id = _extract_video_id(source)
    url = f"https://www.youtube.com/watch?v={video_id}"
    title = _fetch_title(url, video_id)
    text = _fetch_transcript(video_id)

    if not text.strip():
        raise ValueError(f"No transcript available for {source}")

    chapters = [Chapter(title=title, text=text, index=0)]
    return title, chapters


def _extract_video_id(source: str) -> str:
    if _VIDEO_ID_RE.match(source):
        return source
    parsed = urlparse(source)
    if parsed.hostname in ("youtu.be",):
        vid = parsed.path.lstrip("/")
        if vid:
            return vid[:11]
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0][:11]
    raise ValueError(f"Cannot extract video ID from {source}")


def _fetch_title(url: str, video_id: str) -> str:
    """Fetch video title from the page HTML."""
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            page_html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                page_html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return video_id

    match = re.search(r"<title>(.*?)</title>", page_html, re.DOTALL)
    if match:
        title = html.unescape(match.group(1)).strip()
        title = re.sub(r"\s*-\s*YouTube\s*$", "", title).strip()
        if title:
            return title
    return video_id


def _fetch_transcript(video_id: str) -> str:
    """Fetch and join transcript snippets into plain text."""
    ytt = YouTubeTranscriptApi()
    transcript = ytt.fetch(video_id)
    lines = [snippet.text for snippet in transcript.snippets]
    return "\n".join(lines)
