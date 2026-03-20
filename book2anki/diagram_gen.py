"""Generate diagram images using Gemini's image generation API."""
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from book2anki.models import BookImage, Card

_BOOK_IMG_RE = re.compile(r"^\[BOOK-IMG-(\d+)\]$", re.IGNORECASE)

_MODELS = [
    "gemini-3-pro-image-preview",
    "gemini-3.1-flash-image-preview",
]
_MAX_RETRIES = 4

# Approximate cost per image (paid tier, 1K resolution)
_MODEL_COST: dict[str, float] = {
    "gemini-3-pro-image-preview": 0.067,
    "gemini-3.1-flash-image-preview": 0.045,
}


@dataclass
class DiagramResult:
    """Summary of diagram generation."""
    media_files: list[str] = field(default_factory=list)
    generated: int = 0
    cached: int = 0
    failed: int = 0
    model_counts: dict[str, int] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return sum(
            _MODEL_COST.get(m, 0.05) * count
            for m, count in self.model_counts.items()
        )

    @property
    def cost_str(self) -> str:
        c = self.cost
        if c < 0.01:
            return f"${c:.4f}"
        return f"${c:.2f}"

    @property
    def primary_model(self) -> str:
        if not self.model_counts:
            return ""
        return max(self.model_counts, key=lambda m: self.model_counts[m])


def is_gemini_available() -> bool:
    """Check if Gemini image generation is available."""
    if not os.environ.get("GOOGLE_API_KEY"):
        return False
    try:
        from google import genai  # noqa: F401
        return True
    except ImportError:
        return False


def _generate_image(
    prompt: str, api_key: str, filepath: str,
    report_fn: Callable[[str], None] | None = None,
    language: str = "English",
    is_programming: bool = False,
) -> str | None:
    """Call Gemini API to generate an image with retry on 503/429.

    Saves to filepath. Returns model name on success, None on failure.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    if is_programming:
        style = (
            "Use clean technical diagrams: architecture diagrams, "
            "data flow diagrams, system component layouts, or comparison charts. "
            "Use boxes, arrows, and clear labels. Professional whiteboard style."
        )
    else:
        style = (
            "Choose the most appropriate visual style for the subject: "
            "realistic anatomical illustrations for biology and medicine, "
            "maps and timelines for history and geography, "
            "graphs and charts for economics and statistics, "
            "force/circuit/wave diagrams for physics, "
            "concept maps and flowcharts for processes and relationships. "
            "Use realistic depictions where possible, not abstract boxes."
        )

    full_prompt = (
        "Generate a clear, labeled educational image for an Anki flashcard. "
        f"{style} "
        f"White background, readable labels in {language}. "
        f"Subject: {prompt}"
    )

    def _log(msg: str) -> None:
        if report_fn:
            report_fn(msg)

    for model in _MODELS:
        _log(f"trying {model}")
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        image_config=types.ImageConfig(
                            image_size="1K",
                        ),
                    ),
                )

                if not response.parts:
                    return None

                for part in response.parts:
                    if part.inline_data is not None:
                        image = part.as_image()
                        if image is not None:
                            image.save(filepath)
                            return model

                return None

            except Exception as e:
                err = str(e)
                is_retryable = "503" in err or "429" in err or "UNAVAILABLE" in err
                if is_retryable and attempt < _MAX_RETRIES - 1:
                    wait = 5 * (attempt + 1)  # 5s, 10s, 15s, 20s
                    _log(f"{model} unavailable, retry in {wait}s...")
                    time.sleep(wait)
                    continue
                if is_retryable:
                    _log(f"{model} unavailable, trying next model")
                    break  # try next model
                raise

    return None


def _image_filename(card: Card, index: int) -> str:
    """Generate a stable filename for a card's diagram image."""
    key = f"{card.book_title}:{card.chapter_title}:{card.question}"
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"diagram_{h}_{index}.png"


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


def process_diagrams(
    cards: list[Card],
    media_dir: str,
    status_fn: Callable[[str], None] | None = None,
    language: str = "English",
    is_programming: bool = False,
) -> DiagramResult:
    """Generate images for cards that have diagram prompts.

    Modifies cards in place: replaces text prompts with <img> tags.
    Skips cards that already have <img> tags (e.g. from book images).
    Returns DiagramResult with media files, counts, and cost.
    """
    result = DiagramResult()
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return result

    os.makedirs(media_dir, exist_ok=True)

    diagram_cards = [
        (i, c) for i, c in enumerate(cards)
        if c.image.strip() and "<img" not in c.image
    ]

    if not diagram_cards:
        return result

    def _report(msg: str) -> None:
        if status_fn:
            status_fn(msg)

    for seq, (idx, card) in enumerate(diagram_cards):
        prompt = card.image
        filename = _image_filename(card, seq)
        filepath = os.path.join(media_dir, filename)

        # Skip if already generated (resume support)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            _report(f"diagram {seq + 1}/{len(diagram_cards)} (cached)")
            card.image = f'<img src="{filename}">'
            result.media_files.append(filepath)
            result.cached += 1
            continue

        _report(f"diagram {seq + 1}/{len(diagram_cards)}")

        try:
            model_used = _generate_image(
                prompt, api_key, filepath,
                report_fn=_report, language=language,
                is_programming=is_programming,
            )
            if model_used:
                card.image = f'<img src="{filename}">'
                result.media_files.append(filepath)
                result.generated += 1
                result.model_counts[model_used] = (
                    result.model_counts.get(model_used, 0) + 1
                )
            else:
                card.image = ""
                result.failed += 1
        except Exception as e:
            _report(f"diagram {seq + 1} failed: {e}")
            card.diagram = ""
            result.failed += 1

    return result
