import json
import re
import time
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Any, Callable

from book2anki.models import Card, Chapter, TokenUsage
from book2anki.prompts import build_prompt

CHARS_PER_TOKEN = 4

PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
}


def estimate_cost(usage: TokenUsage, model: str) -> float:
    """Estimate cost in USD for given token usage and model."""
    input_rate, output_rate = PRICING.get(model, (0.0, 0.0))
    return (usage.input_tokens * input_rate + usage.output_tokens * output_rate) / 1_000_000


def format_cost(cost: float) -> str:
    """Format cost as a human-readable string."""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        """Send prompt and return (text_response, token_usage)."""
        ...

    @abstractmethod
    def context_window_tokens(self) -> int:
        """Return the model's context window size in tokens."""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for pricing lookup."""
        ...

    def max_request_tokens(self) -> int:
        """Max input tokens per request (for rate limit aware chunking)."""
        return self.context_window_tokens()


def generate_cards_for_chapter(
    provider: LLMProvider,
    chapter: Chapter,
    book_title: str,
    depth: int,
    language: str,
    progress_bar: Any = None,
    is_article: bool = False,
    source_url: str = "",
    is_programming: bool = False,
) -> tuple[list[Card], TokenUsage]:
    """Generate flashcards for a single chapter. Returns (cards, token_usage)."""
    def _status(msg: str) -> None:
        if progress_bar is not None:
            progress_bar.set_postfix_str(msg, refresh=True)
        else:
            print(msg, flush=True)

    short = chapter.title[:60] + "…" if len(chapter.title) > 60 else chapter.title
    _status(f"\"{short}\"")

    book_image_captions: list[tuple[str, str]] | None = None
    if chapter.images:
        book_image_captions = [
            (img.id, img.caption) for img in chapter.images
        ]

    max_text_tokens = min(
        int(provider.context_window_tokens() * 0.8),
        provider.max_request_tokens(),
    )
    prompt_overhead = 500
    output_reserve = 4000
    available_tokens = max_text_tokens - prompt_overhead - output_reserve
    max_chars = available_tokens * CHARS_PER_TOKEN

    # Comprehensive mode generates much more output per input text,
    # so use smaller chunks to avoid server-side timeouts
    if depth == 3:
        max_chars = min(max_chars, 20000)

    total_usage = TokenUsage(0, 0)

    if len(chapter.text) <= max_chars:
        cards, usage = _generate_with_retries(
            provider, chapter.text, book_title, chapter.title, depth, language,
            status_fn=_status, is_article=is_article, source_url=source_url,
            is_programming=is_programming,
            book_image_captions=book_image_captions,
        )
        total_usage += usage
    else:
        chunks = _split_into_chunks(chapter.text, max_chars)
        all_cards: list[Card] = []
        for i, chunk in enumerate(chunks):
            _status(f"\"{short}\" chunk {i + 1}/{len(chunks)}")
            if i > 0:
                time.sleep(5)
            chunk_cards, usage = _generate_with_retries(
                provider, chunk, book_title, chapter.title, depth, language,
                status_fn=_status, is_article=is_article, source_url=source_url,
                is_programming=is_programming,
                book_image_captions=book_image_captions,
            )
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            all_cards.extend(chunk_cards)
        cards = _deduplicate(all_cards)

    valid_cards = [c for c in cards if c.question.strip() and c.answer.strip()]
    return valid_cards, total_usage


def _generate_with_retries(
    provider: LLMProvider,
    text: str,
    book_title: str,
    chapter_title: str,
    depth: int,
    language: str,
    max_retries: int = 3,
    status_fn: Callable[[str], None] | None = None,
    is_article: bool = False,
    source_url: str = "",
    is_programming: bool = False,
    book_image_captions: list[tuple[str, str]] | None = None,
) -> tuple[list[Card], TokenUsage]:
    """Call the LLM and parse JSON response, with retries for failures."""
    prompt = build_prompt(
        book_title, chapter_title, text, depth, language,
        is_article=is_article, is_programming=is_programming,
        book_image_captions=book_image_captions,
    )
    short = chapter_title[:60] + "…" if len(chapter_title) > 60 else chapter_title
    cumulative = TokenUsage(0, 0)

    def _report(msg: str) -> None:
        if status_fn:
            status_fn(msg)

    for attempt in range(max_retries):
        try:
            response, usage = provider.generate(prompt)
            cumulative += usage
            cards_data = _parse_json_response(response)
            return [
                Card(
                    question=item["question"],
                    answer=item["answer"],
                    chapter_title=chapter_title,
                    book_title=book_title,
                    source_url=source_url,
                    example=item.get("example", ""),
                    image=item.get("image", ""),
                )
                for item in cards_data
                if "question" in item and "answer" in item
            ], cumulative
        except (json.JSONDecodeError, KeyError, ValueError):
            if attempt < max_retries - 1:
                _report(f"\"{short}\" parse error, retry {attempt + 2}/{max_retries}")
                time.sleep(1)
                continue
            _report(f"\"{short}\" failed after {max_retries} attempts")
            return [], cumulative
        except Exception as e:
            if attempt < max_retries - 1:
                err_str = str(e)
                if "rate_limit" in err_str or "429" in err_str:
                    wait = 60 * (attempt + 1)
                    _report(f"\"{short}\" rate limited, waiting {wait}s...")
                else:
                    wait = 5 * (2 ** attempt)
                    _report(f"\"{short}\" error, retry in {wait}s...")
                time.sleep(wait)
                _report(f"\"{short}\" retrying ({attempt + 2}/{max_retries})")
                continue
            _report(f"\"{short}\" failed after {max_retries} attempts")
            return [], cumulative

    return [], cumulative


def _parse_json_response(response: str) -> list[dict[str, Any]]:
    """Extract and parse JSON array from LLM response."""
    text = response.strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return list(result)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\[.*?])\s*```", text, re.DOTALL)
    if match:
        result = json.loads(match.group(1))
        return list(result)

    match = re.search(r"\[.*]", text, re.DOTALL)
    if match:
        result = json.loads(match.group(0))
        return list(result)

    raise json.JSONDecodeError("No JSON array found in response", text, 0)


def _split_into_chunks(text: str, max_chars: int, overlap_chars: int = 2000) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            chunks.append(text[start:])
            break

        break_point = text.rfind("\n\n", start + max_chars // 2, end)
        if break_point == -1:
            break_point = text.rfind("\n", start + max_chars // 2, end)
        if break_point == -1:
            break_point = end

        chunks.append(text[start:break_point])
        start = break_point - overlap_chars

    return chunks


def _deduplicate(cards: list[Card], threshold: float = 0.8) -> list[Card]:
    """Remove duplicate cards based on question similarity."""
    unique: list[Card] = []
    for card in cards:
        is_dup = False
        for existing in unique:
            similarity = SequenceMatcher(None, card.question.lower(), existing.question.lower()).ratio()
            if similarity >= threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(card)
    return unique
