import json
import re
import sys
import time
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Any, Callable

from book2anki.models import Card, Chapter, TokenUsage
from book2anki.prompts import build_prompt, build_vocab_prompt

CHARS_PER_TOKEN = 4

PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (15.0, 75.0),
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
    topic: str = "",
    on_chunk_done: Callable[[int, int], None] | None = None,
    parallel_chunks: bool = False,
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
            book_image_captions=book_image_captions, topic=topic,
        )
        total_usage += usage
        if on_chunk_done:
            on_chunk_done(1, 1)
    else:
        chunks = _split_into_chunks(chapter.text, max_chars)
        if on_chunk_done:
            on_chunk_done(0, len(chunks))

        if parallel_chunks:
            all_cards = _process_chunks_parallel(
                chunks, provider, book_title, chapter.title, depth, language,
                total_usage, short, _status, on_chunk_done,
                is_article=is_article, source_url=source_url,
                is_programming=is_programming,
                book_image_captions=book_image_captions, topic=topic,
            )
        else:
            all_cards = _process_chunks_sequential(
                chunks, provider, book_title, chapter.title, depth, language,
                total_usage, short, _status, on_chunk_done,
                is_article=is_article, source_url=source_url,
                is_programming=is_programming,
                book_image_captions=book_image_captions, topic=topic,
            )
        cards = deduplicate(all_cards)

    valid_cards = [c for c in cards if c.question.strip() and c.answer.strip()]
    return valid_cards, total_usage


def _process_chunks_sequential(
    chunks: list[str],
    provider: LLMProvider,
    book_title: str,
    chapter_title: str,
    depth: int,
    language: str,
    total_usage: TokenUsage,
    short: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
    **kwargs: Any,
) -> list[Card]:
    all_cards: list[Card] = []
    for i, chunk in enumerate(chunks):
        status_fn(f"\"{short}\" chunk {i + 1}/{len(chunks)}")
        if i > 0:
            time.sleep(5)
        chunk_cards, usage = _generate_with_retries(
            provider, chunk, book_title, chapter_title, depth, language,
            status_fn=status_fn, **kwargs,
        )
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        all_cards.extend(chunk_cards)
        if on_chunk_done:
            on_chunk_done(i + 1, len(chunks))
    return all_cards


def _process_chunks_parallel(
    chunks: list[str],
    provider: LLMProvider,
    book_title: str,
    chapter_title: str,
    depth: int,
    language: str,
    total_usage: TokenUsage,
    short: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
    **kwargs: Any,
) -> list[Card]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # cards_by_index preserves chunk order
    cards_by_index: dict[int, list[Card]] = {}
    futures = {}
    done_count = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        for i, chunk in enumerate(chunks):
            futures[executor.submit(
                _generate_with_retries,
                provider, chunk, book_title, chapter_title, depth, language,
                status_fn=lambda _msg: None,  # suppress per-chunk status in parallel
                **kwargs,
            )] = i

        for future in as_completed(futures):
            idx = futures[future]
            try:
                chunk_cards, usage = future.result()
                cards_by_index[idx] = chunk_cards
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                done_count += 1
                status_fn(f"\"{short}\" chunks {done_count}/{len(chunks)}")
                if on_chunk_done:
                    on_chunk_done(done_count, len(chunks))
            except Exception as e:
                print(f"  chunk {idx + 1} failed: {e}", file=sys.stderr)
                done_count += 1
                if on_chunk_done:
                    on_chunk_done(done_count, len(chunks))

    # Return cards in chunk order
    all_cards: list[Card] = []
    for idx in sorted(cards_by_index):
        all_cards.extend(cards_by_index[idx])
    return all_cards


def generate_vocab_for_chapter(
    provider: LLMProvider,
    chapter: Chapter,
    book_title: str,
    level: str,
    native_language: str,
    progress_bar: Any = None,
    is_article: bool = False,
    topic: str = "",
    on_chunk_done: Callable[[int, int], None] | None = None,
    parallel_chunks: bool = False,
) -> tuple[list[Card], TokenUsage]:
    """Extract vocabulary cards for a single chapter. Returns (cards, token_usage)."""
    def _status(msg: str) -> None:
        if progress_bar is not None:
            progress_bar.set_postfix_str(msg, refresh=True)
        else:
            print(msg, flush=True)

    short = chapter.title[:60] + "…" if len(chapter.title) > 60 else chapter.title
    _status(f"\"{short}\"")

    max_text_tokens = min(
        int(provider.context_window_tokens() * 0.8),
        provider.max_request_tokens(),
    )
    prompt_overhead = 500
    output_reserve = 4000
    available_tokens = max_text_tokens - prompt_overhead - output_reserve
    max_chars = available_tokens * CHARS_PER_TOKEN

    # Vocab generates many fields per word — use smaller chunks
    # to avoid output truncation at max_tokens
    max_chars = min(max_chars, 20000)

    total_usage = TokenUsage(0, 0)

    if len(chapter.text) <= max_chars:
        cards, usage = _generate_vocab_with_retries(
            provider, chapter.text, book_title, chapter.title,
            level, native_language,
            status_fn=_status, is_article=is_article, topic=topic,
        )
        total_usage += usage
        if on_chunk_done:
            on_chunk_done(1, 1)
    else:
        chunks = _split_into_chunks(chapter.text, max_chars)
        if on_chunk_done:
            on_chunk_done(0, len(chunks))

        if parallel_chunks:
            all_cards = _process_vocab_chunks_parallel(
                chunks, provider, book_title, chapter.title,
                level, native_language, total_usage, short, _status, on_chunk_done,
                is_article=is_article, topic=topic,
            )
        else:
            all_cards = []
            for i, chunk in enumerate(chunks):
                _status(f"\"{short}\" chunk {i + 1}/{len(chunks)}")
                if i > 0:
                    time.sleep(5)
                chunk_cards, usage = _generate_vocab_with_retries(
                    provider, chunk, book_title, chapter.title,
                    level, native_language,
                    status_fn=_status, is_article=is_article, topic=topic,
                )
                total_usage += usage
                all_cards.extend(chunk_cards)
                if on_chunk_done:
                    on_chunk_done(i + 1, len(chunks))
        cards = deduplicate_vocab(all_cards)

    valid_cards = [c for c in cards if c.question.strip() and c.answer.strip()]
    return valid_cards, total_usage


def _process_vocab_chunks_parallel(
    chunks: list[str],
    provider: LLMProvider,
    book_title: str,
    chapter_title: str,
    level: str,
    native_language: str,
    total_usage: TokenUsage,
    short: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
    **kwargs: Any,
) -> list[Card]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cards_by_index: dict[int, list[Card]] = {}
    futures = {}
    done_count = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        for i, chunk in enumerate(chunks):
            futures[executor.submit(
                _generate_vocab_with_retries,
                provider, chunk, book_title, chapter_title,
                level, native_language,
                status_fn=lambda _msg: None,
                **kwargs,
            )] = i

        for future in as_completed(futures):
            idx = futures[future]
            try:
                chunk_cards, usage = future.result()
                cards_by_index[idx] = chunk_cards
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                done_count += 1
                status_fn(f"\"{short}\" chunks {done_count}/{len(chunks)}")
                if on_chunk_done:
                    on_chunk_done(done_count, len(chunks))
            except Exception as e:
                print(f"  chunk {idx + 1} failed: {e}", file=sys.stderr)
                done_count += 1
                if on_chunk_done:
                    on_chunk_done(done_count, len(chunks))

    all_cards: list[Card] = []
    for idx in sorted(cards_by_index):
        all_cards.extend(cards_by_index[idx])
    return all_cards


def _generate_vocab_with_retries(
    provider: LLMProvider,
    text: str,
    book_title: str,
    chapter_title: str,
    level: str,
    native_language: str,
    max_retries: int = 3,
    status_fn: Callable[[str], None] | None = None,
    is_article: bool = False,
    topic: str = "",
) -> tuple[list[Card], TokenUsage]:
    """Call LLM with vocab prompt and parse response, with retries."""
    prompt = build_vocab_prompt(
        book_title, chapter_title, text, level, native_language,
        is_article=is_article, topic=topic,
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
            cards = []
            for item in cards_data:
                if "word" not in item:
                    continue
                word = item["word"]
                pronunciation = item.get("pronunciation", "")
                if pronunciation:
                    word += f'<div class="ipa">{pronunciation}</div>'
                definition = item.get("definition", "")
                etymology = item.get("etymology", "")
                if etymology:
                    definition += f'<div class="etymology">{etymology}</div>'
                cards.append(Card(
                    question=word,
                    answer=item.get("translation", ""),
                    chapter_title=chapter_title,
                    book_title=book_title,
                    example=item.get("context", ""),
                    image=definition,
                    source_url=item.get("example", ""),
                ))
            return cards, cumulative
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            if attempt < max_retries - 1:
                preview = response[:500] if response else "(empty)"
                print(f"\n\"{short}\" parse error: {e}", file=sys.stderr)
                print(f"\"{short}\" response preview: {preview}", file=sys.stderr)
                _report(f"\"{short}\" retrying ({attempt + 2}/{max_retries})")
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
                    print(f"\n\"{short}\" error: {type(e).__name__}: {str(e)[:300]}",
                          file=sys.stderr)
                    _report(f"\"{short}\" retry in {wait}s...")
                time.sleep(wait)
                _report(f"\"{short}\" retrying ({attempt + 2}/{max_retries})")
                continue
            print(f"\n\"{short}\" failed: {type(e).__name__}: {str(e)[:300]}",
                  file=sys.stderr)
            return [], cumulative

    return [], cumulative


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
    topic: str = "",
) -> tuple[list[Card], TokenUsage]:
    """Call the LLM and parse JSON response, with retries for failures."""
    prompt = build_prompt(
        book_title, chapter_title, text, depth, language,
        is_article=is_article, is_programming=is_programming,
        book_image_captions=book_image_captions, topic=topic,
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
        try:
            result = json.loads(match.group(0))
            return list(result)
        except json.JSONDecodeError:
            pass

    # Try to salvage truncated JSON — find the last complete object
    result = _salvage_truncated_json(text)
    if result:
        return result

    raise json.JSONDecodeError("No JSON array found in response", text, 0)


def _salvage_truncated_json(text: str) -> list[dict[str, Any]]:
    """Try to recover complete objects from a truncated JSON array."""
    start = text.find("[")
    if start == -1:
        return []
    text = text[start:]

    # Find the last complete "}, " or "}," and close the array
    last = text.rfind("}")
    while last > 0:
        candidate = text[:last + 1] + "]"
        try:
            result = json.loads(candidate)
            if isinstance(result, list) and result:
                return list(result)
        except json.JSONDecodeError:
            pass
        last = text.rfind("}", 0, last)

    return []


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


def deduplicate(cards: list[Card], threshold: float = 0.8) -> list[Card]:
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


def vocab_word(question: str) -> str:
    """Extract just the word from a vocab question field (strip IPA div)."""
    return question.split("<div", 1)[0].strip().lower()


def _vocab_base(word: str) -> str:
    """Normalize a vocab word for dedup comparison.

    Strips articles, 'to ' prefix, reflexive suffixes, and
    parenthetical notes like (n.), (der), (м/ж) etc.
    """
    w = word.lower().strip()
    # Strip IPA transcription: /ˈkɒk.ər.əl/ or [ˈkɒk.ər.əl]
    w = re.sub(r"\s*/[^/]+/\s*", " ", w).strip()
    w = re.sub(r"\s*\[.*?\]\s*", " ", w).strip()
    # Strip parenthetical grammar notes: "cockerel (n.)" → "cockerel"
    w = re.sub(r"\s*\(.*?\)\s*", " ", w).strip()
    # Strip articles
    for article in ("a ", "an ", "the ", "der ", "die ", "das ",
                    "le ", "la ", "les ", "un ", "une "):
        if w.startswith(article):
            w = w[len(article):]
            break
    for prefix in ("to ", "sich "):
        if w.startswith(prefix):
            w = w[len(prefix):]
            break
    # Strip reflexive: "ensconce oneself" → "ensconce"
    for suffix in (" oneself", " itself", " himself", " herself",
                   " themselves", " myself", " yourself", " ourselves",
                   " sich", " se"):
        if w.endswith(suffix):
            w = w[:-len(suffix)]
            break
    # Strip trailing gender markers: "cockerel, m" or "петух м"
    w = re.sub(r"[,\s]+(m|f|n|м|ж|ср)\.?$", "", w)
    return w.strip()


_SEP = '<div class="sep"></div>'


def _bold_word_in_context(context: str, word: str) -> str:
    """Bold the target word in a context sentence if not already bolded."""
    if "<b>" in context:
        return context
    pattern = re.compile(re.escape(word), re.IGNORECASE)
    return pattern.sub(lambda m: f"<b>{m.group(0)}</b>", context, count=1)


def deduplicate_vocab(cards: list[Card],
                      max_contexts: int = 3) -> list[Card]:
    """Merge duplicate vocab cards, combining context sentences up to max_contexts."""
    unique: list[Card] = []
    for card in cards:
        merged = False
        for existing in unique:
            word = vocab_word(existing.question)
            if _vocab_base(vocab_word(card.question)) == _vocab_base(word):
                # Move extra contexts to answer side (source_url = examples)
                all_examples = [
                    _bold_word_in_context(e, word)
                    for e in existing.source_url.split(_SEP) if e.strip()
                ]
                if card.example and card.example != existing.example:
                    bolded = _bold_word_in_context(card.example, word)
                    if len(all_examples) < max_contexts and bolded not in all_examples:
                        all_examples.append(bolded)
                if card.source_url:
                    for ex in card.source_url.split(_SEP):
                        ex = ex.strip()
                        if not ex or len(all_examples) >= max_contexts:
                            continue
                        bolded = _bold_word_in_context(ex, word)
                        if bolded not in all_examples:
                            all_examples.append(bolded)
                existing.source_url = _SEP.join(all_examples)
                merged = True
                break
        if not merged:
            unique.append(card)
    return unique


def consolidate_cards(
    provider: LLMProvider,
    cards: list[Card],
    language: str,
) -> tuple[list[Card], TokenUsage]:
    """Use LLM to remove duplicate/overlapping cards, keeping the best version."""
    if len(cards) <= 3:
        return cards, TokenUsage(0, 0)

    cards_json = json.dumps([
        {"id": i, "question": c.question, "answer": c.answer}
        for i, c in enumerate(cards)
    ], ensure_ascii=False, indent=2)

    prompt = f"""You are reviewing a set of Anki flashcards generated from a book.

Some cards may be duplicates or near-duplicates — same concept asked in slightly different ways.
Your job: remove redundant cards, keeping the best-worded version of each unique concept.

Rules:
- Return ONLY the IDs of cards to KEEP (not remove)
- If two cards test the same concept, keep whichever has the better question and answer
- Do NOT remove cards that test related but distinct concepts
- Output a JSON array of integer IDs, nothing else

Language: {language}

Cards:
{cards_json}

Return the JSON array of IDs to keep:"""

    try:
        response, usage = provider.generate(prompt)
        text = response.strip()
        # Parse the ID list
        match = re.search(r"\[[\d\s,]*]", text)
        if match:
            keep_ids = set(json.loads(match.group(0)))
            kept = [c for i, c in enumerate(cards) if i in keep_ids]
            if kept:
                return kept, usage
    except Exception:
        pass

    return cards, TokenUsage(0, 0)
