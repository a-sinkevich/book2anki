"""Process book images for Anki cards."""
import hashlib
import os
import re

from book2anki.models import BookImage, Card

_BOOK_IMG_RE = re.compile(r"^\[BOOK-IMG-(\d+)\]$", re.IGNORECASE)


def _book_img_filename(image: BookImage, card: Card) -> str:
    """Generate a stable filename for a book image."""
    h = hashlib.md5(image.data[:1024]).hexdigest()[:10]
    return f"bookimg_{h}.{image.ext}"


def process_book_images(
    cards: list[Card],
    images: list[BookImage],
    media_dir: str,
) -> list[str]:
    """Resolve [BOOK-IMG-N] references in card image fields.

    Saves referenced images to media_dir, replaces references with <img> tags
    and captions. Returns list of media file paths.
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

        filename = _book_img_filename(image, card)
        filepath = os.path.join(media_dir, filename)
        if not os.path.exists(filepath):
            with open(filepath, "wb") as f:
                f.write(image.data)
        caption_html = ""
        if image.caption:
            caption_html = f'<div class="image-caption">{image.caption}</div>'
        card.image = f'<img src="{filename}">{caption_html}'
        if filepath not in media_files:
            media_files.append(filepath)

    return media_files
