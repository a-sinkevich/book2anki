"""Process book/web images for Anki cards."""
import hashlib
import os
import re
import ssl
import urllib.request

from book2anki.models import BookImage, Card

_BOOK_IMG_RE = re.compile(r"^\[BOOK-IMG-(\d+)\]$", re.IGNORECASE)


def _fetch_image(url: str) -> bytes:
    """Download image data from a URL."""
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                return resp.read()
        raise


def _get_image_data(image: BookImage) -> bytes:
    """Get image data, downloading from URL if needed."""
    if image.data:
        return image.data
    if image.url:
        image.data = _fetch_image(image.url)
        return image.data
    return b""


def _image_filename(image: BookImage) -> str:
    """Generate a stable filename for an image."""
    data = _get_image_data(image)
    h = hashlib.md5(data[:1024]).hexdigest()[:10]
    return f"bookimg_{h}.{image.ext}"


def process_book_images(
    cards: list[Card],
    images: list[BookImage],
    media_dir: str,
) -> list[str]:
    """Resolve [BOOK-IMG-N] references in card image fields.

    Saves referenced images to media_dir, replaces references with <img> tags
    and captions. Only downloads URL-based images if actually referenced.
    Returns list of media file paths.
    """
    if not images:
        return []

    image_by_num: dict[int, BookImage] = {}
    for img in images:
        parts = img.id.rsplit("-", 1)
        if parts:
            try:
                image_by_num[int(parts[-1])] = img
            except ValueError:
                pass

    os.makedirs(media_dir, exist_ok=True)
    media_files: list[str] = []

    for card in cards:
        if not card.image.strip():
            continue
        m = _BOOK_IMG_RE.match(card.image.strip())
        if not m:
            continue
        num = int(m.group(1))
        image = image_by_num.get(num)
        if not image:
            card.image = ""
            continue

        try:
            data = _get_image_data(image)
        except Exception:
            card.image = ""
            continue
        if not data:
            card.image = ""
            continue

        filename = _image_filename(image)
        filepath = os.path.join(media_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, "wb") as f:
                f.write(data)
        caption_html = ""
        if image.caption:
            caption_html = f'<div class="image-caption">{image.caption}</div>'
        card.image = f'<img src="{filename}">{caption_html}'
        if filepath not in media_files:
            media_files.append(filepath)

    return media_files
