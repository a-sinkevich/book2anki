import json
import re
import time
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Any, Callable, TypeVar

from book2anki.models import CLOZE_TAG, Card, Chapter
from book2anki.prompts import (
    build_prompt, build_prompt_request, build_vocab_prompt, build_practice_prompt,
)

CHARS_PER_TOKEN = 4

# Max concurrent LLM requests when --parallel is set (chapters and chunks)
PARALLEL_WORKERS = 8

# Attempts per request. Covers rate limits, dropped connections and unparseable
# replies; also the claude CLI's habit of returning an empty result instantly.
GENERATION_ATTEMPTS = 3

# Pause between sequential chunks of the same chapter, to stay under rate limits
CHUNK_PAUSE_SECONDS = 5

# Errors collected during generation (printed after progress table closes)
generation_errors: list[str] = []

T = TypeVar("T")

# Short names accepted by --model, resolved to exact model IDs. Bump these when
# a new generation ships: the CLI and API providers both read this map, so the
# two cannot drift apart.
MODEL_ALIASES = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
}


def resolve_model(name: str) -> str:
    """Resolve a --model shortcut to an exact model ID; pass exact IDs through."""
    return MODEL_ALIASES.get(name, name)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Send prompt and return the model's text response."""
        ...

    @abstractmethod
    def context_window_tokens(self) -> int:
        """Return the model's context window size in tokens."""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        ...

    def max_request_tokens(self) -> int:
        """Max input tokens per request (for rate limit aware chunking)."""
        return self.context_window_tokens()


def _is_cli_provider(provider: LLMProvider) -> bool:
    """Return True for local CLI-backed providers where empty fast returns happen."""
    return provider.model_name().startswith(("cli:", "codex:"))


def _retries_empty(provider: LLMProvider, topic: str) -> bool:
    """Whether an empty-but-valid reply is worth another attempt.

    Only for CLI providers, and only without a topic filter — a topic run
    legitimately finds nothing in most chapters.
    """
    return _is_cli_provider(provider) and not topic


def _short_label(title: str) -> str:
    """Truncate a chapter title for status lines."""
    return title[:60] + "…" if len(title) > 60 else title


def _status_fn(progress_bar: Any) -> Callable[[str], None]:
    """Route status messages to the progress bar, or to stdout when there is none."""
    if progress_bar is None:
        return lambda msg: print(msg, flush=True)
    return lambda msg: progress_bar.set_postfix_str(msg, refresh=True)


def _backoff_seconds(error: Exception, attempt: int) -> float:
    """How long to wait before retrying: long for rate limits, exponential otherwise."""
    text = str(error)
    if "rate_limit" in text or "429" in text:
        return 60.0 * (attempt + 1)
    return 5.0 * 2.0 ** attempt


def _generate_parsed(
    provider: LLMProvider,
    prompt: str,
    label: str,
    parse: Callable[[str], T],
    status_fn: Callable[[str], None] | None = None,
    retry_empty: bool = False,
    report_empty: bool = False,
    is_empty: Callable[[T], bool] | None = None,
) -> T | None:
    """Call the model, parse the reply, and retry transient failures.

    Rate limits, dropped connections and unparseable replies are all retried up
    to GENERATION_ATTEMPTS times. An empty-but-valid reply is only retried when
    `retry_empty` is set: an API model that answers "[]" means it, while the
    claude CLI returns one spuriously. `report_empty` records a final empty
    reply in `generation_errors`, so a silently skipped chapter stays visible.

    Returns None when every attempt failed; callers supply their own empty value.
    """
    empty = is_empty or (lambda result: not result)

    def report(msg: str) -> None:
        if status_fn:
            status_fn(msg)

    last_error = ""
    for attempt in range(GENERATION_ATTEMPTS):
        remaining = GENERATION_ATTEMPTS - attempt - 1
        response = ""
        try:
            response = provider.generate(prompt)
            result = parse(response)
            if empty(result):
                if retry_empty and remaining:
                    report(f'"{label}" returned 0 cards, '
                           f"retrying ({attempt + 2}/{GENERATION_ATTEMPTS})")
                    time.sleep(1)
                    continue
                if report_empty:
                    generation_errors.append(
                        f'"{label}": model returned 0 cards '
                        f"(response: {response[:200] or '(empty)'})"
                    )
            return result
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = (f"parse error: {e} | "
                          f"response: {response[:300] or '(empty)'}")
            wait = 1.0
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:500]}"
            wait = _backoff_seconds(e, attempt)

        if not remaining:
            break
        report(f'"{label}" failed, retry {attempt + 2}/'
               f"{GENERATION_ATTEMPTS} in {wait:.0f}s")
        time.sleep(wait)

    report(f'"{label}" failed after {GENERATION_ATTEMPTS} attempts')
    generation_errors.append(f'"{label}": {last_error}')
    return None


ChunkWork = Callable[[str, Callable[[str], None]], list[Card]]


def _run_chunks(
    chunks: list[str],
    work: ChunkWork,
    label: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
    parallel: bool,
) -> list[Card]:
    """Run `work` over every chunk, returning the cards in chunk order."""
    if on_chunk_done:
        on_chunk_done(0, len(chunks))
    if parallel:
        return _run_chunks_parallel(chunks, work, label, status_fn, on_chunk_done)
    return _run_chunks_sequential(chunks, work, label, status_fn, on_chunk_done)


def _run_chunks_sequential(
    chunks: list[str],
    work: ChunkWork,
    label: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
) -> list[Card]:
    cards: list[Card] = []
    for i, chunk in enumerate(chunks):
        status_fn(f'"{label}" chunk {i + 1}/{len(chunks)}')
        if i > 0:
            time.sleep(CHUNK_PAUSE_SECONDS)
        cards.extend(work(chunk, status_fn))
        if on_chunk_done:
            on_chunk_done(i + 1, len(chunks))
    return cards


def _run_chunks_parallel(
    chunks: list[str],
    work: ChunkWork,
    label: str,
    status_fn: Callable[[str], None],
    on_chunk_done: Callable[[int, int], None] | None,
) -> list[Card]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _quiet(_msg: str) -> None:
        """Per-chunk status is noise once chunks interleave."""

    cards_by_index: dict[int, list[Card]] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(work, chunk, _quiet): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                cards_by_index[idx] = future.result()
            except Exception as e:
                generation_errors.append(
                    f'"{label}" chunk {idx + 1}/{len(chunks)}: '
                    f"{type(e).__name__}: {str(e)[:300]}"
                )
            done += 1
            status_fn(f'"{label}" chunks {done}/{len(chunks)}')
            if on_chunk_done:
                on_chunk_done(done, len(chunks))

    return [card for idx in sorted(cards_by_index) for card in cards_by_index[idx]]


def _chunk_budget(
    provider: LLMProvider,
    prompt_overhead: int,
    output_reserve: int,
    cap: int = 0,
) -> int:
    """Max characters of source text to put in one request."""
    max_text_tokens = min(
        int(provider.context_window_tokens() * 0.8),
        provider.max_request_tokens(),
    )
    available_tokens = max_text_tokens - prompt_overhead - output_reserve
    max_chars = available_tokens * CHARS_PER_TOKEN
    if cap:
        max_chars = min(max_chars, cap)
    return max_chars


def _chapter_cards(
    chapter: Chapter,
    max_chars: int,
    work: ChunkWork,
    dedup: Callable[[list[Card]], list[Card]],
    progress_bar: Any,
    on_chunk_done: Callable[[int, int], None] | None,
    parallel_chunks: bool,
) -> list[Card]:
    """Run `work` over a chapter, splitting the text when it exceeds max_chars."""
    status = _status_fn(progress_bar)
    label = _short_label(chapter.title)
    status(f'"{label}"')

    if len(chapter.text) <= max_chars:
        cards = work(chapter.text, status)
        if on_chunk_done:
            on_chunk_done(1, 1)
    else:
        chunks = _split_into_chunks(chapter.text, max_chars)
        cards = dedup(_run_chunks(
            chunks, work, label, status, on_chunk_done, parallel_chunks,
        ))

    return [c for c in cards if c.question.strip() and c.answer.strip()]


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
    is_transcript: bool = False,
) -> list[Card]:
    """Generate flashcards for a single chapter."""
    book_image_captions: list[tuple[str, str]] | None = None
    if chapter.images:
        book_image_captions = [(img.id, img.caption) for img in chapter.images]

    # Comprehensive mode generates much more output per input text,
    # so use smaller chunks to avoid server-side timeouts
    cap = 20000 if depth == 3 else 0
    max_chars = _chunk_budget(provider, 500, 4000, cap)

    def work(text: str, status: Callable[[str], None]) -> list[Card]:
        return _generate_with_retries(
            provider, text, book_title, chapter.title, depth, language,
            status_fn=status, is_article=is_article, source_url=source_url,
            is_programming=is_programming,
            book_image_captions=book_image_captions, topic=topic,
            is_transcript=is_transcript,
        )

    return _chapter_cards(
        chapter, max_chars, work, deduplicate,
        progress_bar, on_chunk_done, parallel_chunks,
    )


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
) -> list[Card]:
    """Extract vocabulary cards for a single chapter."""
    # Vocab generates many fields per word — use smaller chunks
    # to avoid output truncation at max_tokens
    max_chars = _chunk_budget(provider, 500, 4000, cap=20000)

    def work(text: str, status: Callable[[str], None]) -> list[Card]:
        return _generate_vocab_with_retries(
            provider, text, book_title, chapter.title, level, native_language,
            status_fn=status, is_article=is_article, topic=topic,
        )

    return _chapter_cards(
        chapter, max_chars, work, deduplicate_vocab,
        progress_bar, on_chunk_done, parallel_chunks,
    )


def generate_practice_for_chapter(
    provider: LLMProvider,
    chapter: Chapter,
    book_title: str,
    depth: int,
    progress_bar: Any = None,
    topic: str = "",
    code_lang: str = "",
    on_chunk_done: Callable[[int, int], None] | None = None,
    parallel_chunks: bool = False,
) -> list[Card]:
    """Generate programming practice exercise cards for a single chapter."""
    # The practice prompt is larger and its cards (especially katas) run long,
    # so reserve more output room; comprehensive mode runs longer still.
    cap = 20000 if depth == 3 else 0
    max_chars = _chunk_budget(provider, 1000, 8000, cap)

    def work(text: str, status: Callable[[str], None]) -> list[Card]:
        return _generate_practice_with_retries(
            provider, text, book_title, chapter.title, depth,
            status_fn=status, topic=topic, code_lang=code_lang,
        )

    return _chapter_cards(
        chapter, max_chars, work, deduplicate,
        progress_bar, on_chunk_done, parallel_chunks,
    )


def _generate_with_retries(
    provider: LLMProvider,
    text: str,
    book_title: str,
    chapter_title: str,
    depth: int,
    language: str,
    status_fn: Callable[[str], None] | None = None,
    is_article: bool = False,
    source_url: str = "",
    is_programming: bool = False,
    book_image_captions: list[tuple[str, str]] | None = None,
    topic: str = "",
    is_transcript: bool = False,
) -> list[Card]:
    """Generate cards for one piece of text, retrying transient failures."""
    prompt = build_prompt(
        book_title, chapter_title, text, depth, language,
        is_article=is_article, is_programming=is_programming,
        book_image_captions=book_image_captions, topic=topic,
        is_transcript=is_transcript,
    )

    def parse(response: str) -> list[Card]:
        cards = []
        for item in _parse_json_response(response):
            if "question" not in item or "answer" not in item:
                continue
            if is_transcript and _CLOZE_RE.search(item["question"]):
                # Cloze quotes the source verbatim, which a machine transcript
                # cannot support; the prompt says so, and a stray one has no
                # sane rendering, so drop it rather than ship a broken card.
                continue
            question, tags = _question_and_tags(item)
            cards.append(Card(
                question=question,
                answer=item["answer"],
                chapter_title=chapter_title,
                book_title=book_title,
                source_url=source_url,
                example=item.get("example", ""),
                image=item.get("image", ""),
                tags=tags,
            ))
        return cards

    cards = _generate_parsed(
        provider, prompt, _short_label(chapter_title), parse,
        status_fn=status_fn,
        retry_empty=_retries_empty(provider, topic),
        report_empty=not topic,
    )
    return cards or []


# Anki cloze deletion: {{c1::answer}} or {{c1::answer::hint}}
_CLOZE_RE = re.compile(r"\{\{c\d+::(.+?)(?:::.*?)?}}", re.DOTALL)


def _question_and_tags(item: dict[str, Any]) -> tuple[str, list[str]]:
    """Build a card's question field, marking and decorating cloze items.

    The deletion itself decides, not the model's `"type"` claim. A `{{c1::…}}`
    left unlabelled would otherwise render as literal braces on a basic note,
    and a card labelled `"cloze"` with no deletion in it would produce a note
    Anki generates no cards from. An optional `context` becomes an orienting
    line above the sentence, shown on both sides of the card.
    """
    question = item["question"]
    if not _CLOZE_RE.search(question):
        return question, []

    context = str(item.get("context", "")).strip()
    if context:
        question = f'<div class="cloze-context">{context}</div>{question}'
    return question, [CLOZE_TAG]


def _cloze_terms(question: str) -> set[str]:
    """The hidden answers in a cloze question, normalized for comparison."""
    return {
        re.sub(r"<[^>]+>", "", term).strip().lower()
        for term in _CLOZE_RE.findall(question)
    }


def _generate_vocab_with_retries(
    provider: LLMProvider,
    text: str,
    book_title: str,
    chapter_title: str,
    level: str,
    native_language: str,
    status_fn: Callable[[str], None] | None = None,
    is_article: bool = False,
    topic: str = "",
) -> list[Card]:
    """Extract vocabulary from one piece of text, retrying transient failures."""
    prompt = build_vocab_prompt(
        book_title, chapter_title, text, level, native_language,
        is_article=is_article, topic=topic,
    )

    def parse(response: str) -> list[Card]:
        cards = []
        for item in _parse_json_response(response):
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
        return cards

    cards = _generate_parsed(
        provider, prompt, _short_label(chapter_title), parse,
        status_fn=status_fn,
        retry_empty=_retries_empty(provider, topic),
    )
    return cards or []


def _generate_practice_with_retries(
    provider: LLMProvider,
    text: str,
    book_title: str,
    chapter_title: str,
    depth: int,
    status_fn: Callable[[str], None] | None = None,
    topic: str = "",
    code_lang: str = "",
) -> list[Card]:
    """Generate practice exercises for one piece of text, retrying failures."""
    prompt = build_practice_prompt(
        book_title, chapter_title, text, depth, topic=topic, code_lang=code_lang,
    )

    def parse(response: str) -> list[Card]:
        return [
            Card(
                question=item["question"],
                answer=item["answer"],
                chapter_title=chapter_title,
                book_title=book_title,
                example=item.get("example", ""),
            )
            for item in _parse_json_response(response)
            if "question" in item and "answer" in item
        ]

    cards = _generate_parsed(
        provider, prompt, _short_label(chapter_title), parse,
        status_fn=status_fn,
        retry_empty=_retries_empty(provider, topic),
    )
    return cards or []


def generate_cards_for_prompt(
    provider: LLMProvider,
    request: str,
    fallback_title: str,
    depth: int,
    language: str,
    status_fn: Callable[[str], None] | None = None,
) -> tuple[str, list[Card]]:
    """Generate standalone cards from a source-free study request."""
    prompt = build_prompt_request(request, depth, language)

    def parse(response: str) -> tuple[str, list[Card]]:
        deck_title, cards_data = _parse_prompt_response(response)
        deck_title = deck_title or fallback_title
        return deck_title, [
            Card(
                question=item["question"],
                answer=item["answer"],
                chapter_title="Generated Study Guide",
                book_title=deck_title,
                source_url=request,
                example=item.get("example", ""),
                tags=["source::prompt"],
            )
            for item in cards_data
            if "question" in item and "answer" in item
        ]

    result = _generate_parsed(
        provider, prompt, _short_label(fallback_title), parse,
        status_fn=status_fn,
        retry_empty=_retries_empty(provider, ""),
        is_empty=lambda parsed: not parsed[1],
    )
    return result or (fallback_title, [])


def _parse_prompt_response(response: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse prompt-mode response, accepting the current object shape and old arrays."""
    text = response.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = None

    if isinstance(result, dict):
        return _prompt_result_parts(result)
    if isinstance(result, list):
        return "", list(result)

    match = re.search(r"```(?:json)?\s*(\{.*?})\s*```", text, re.DOTALL)
    if match:
        result = json.loads(match.group(1))
        if isinstance(result, dict):
            return _prompt_result_parts(result)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        result = json.loads(text[start:end + 1])
        if isinstance(result, dict):
            return _prompt_result_parts(result)

    cards = _parse_json_response(response)
    return "", cards


def _prompt_result_parts(result: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Extract title and cards from a parsed prompt-mode JSON object."""
    title = str(result.get("title", "")).strip()
    cards = result.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Prompt response 'cards' must be an array")
    return title, list(cards)


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
    """Split text into overlapping chunks.

    The overlap is capped at a quarter of the chunk size so every chunk starts
    after the previous one did: a break point can land as early as
    max_chars // 2, and a larger overlap would rewind `start` and loop forever.
    """
    max_chars = max(1, max_chars)
    overlap_chars = max(0, min(overlap_chars, max_chars // 4))

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
    """Remove duplicate cards.

    Cloze cards are matched on the term they hide, since two different sentences
    concealing the same word teach the same thing and their surrounding text is
    too dissimilar for the similarity check to catch. Everything else is matched
    on question similarity. A cloze card never displaces the concept card about
    the same term — those are the two directions we deliberately want.
    """
    unique: list[Card] = []
    seen_terms: set[str] = set()
    for card in cards:
        terms = _cloze_terms(card.question)
        if terms:
            if terms & seen_terms:
                continue
            seen_terms |= terms
            unique.append(card)
            continue
        is_dup = False
        for existing in unique:
            if _cloze_terms(existing.question):
                continue
            similarity = SequenceMatcher(None, card.question.lower(), existing.question.lower()).ratio()
            if similarity >= threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(card)
    return unique


def vocab_word(question: str) -> str:
    """Extract just the word from a vocab question field (strip HTML/IPA)."""
    # Strip everything from first HTML tag onward (<div>, <br>, etc.)
    w = re.split(r"<\w", question, maxsplit=1)[0]
    # Also strip IPA on same line: "word /ipa/" or after newline
    w = w.split("\n")[0]
    return w.strip().lower()


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


def _gap_key(context: str) -> str:
    """Context sentence with the target word blanked, normalized.

    Two cards generated from the same sentence (but with different — possibly
    misspelled — headwords) share the same gap key, which lets us recognize
    them as the same word.
    """
    if not context:
        return ""
    s = re.sub(r"<b>.*?</b>", "\x00", context, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _context_word(context: str) -> str:
    """The actual word highlighted in a context sentence (book's real spelling)."""
    m = re.search(r"<b>(.*?)</b>", context, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip().lower()


def _spelling_score(word: str, truth: str) -> float:
    """How closely a headword matches the book's actual word (0..1, -1 if unknown)."""
    if not truth:
        return -1.0
    return SequenceMatcher(None, word, truth).ratio()


def deduplicate_vocab(cards: list[Card],
                      max_contexts: int = 3) -> list[Card]:
    """Merge duplicate vocab cards, combining context sentences up to max_contexts.

    Two cards are the same word if their normalized base forms match, or if they
    were drawn from the same context sentence (different spellings of the same
    word — an LLM spelling variant). When variants merge, the headword whose
    spelling best matches the book's actual highlighted word is kept, so
    misspellings/hallucinations are dropped.
    """
    unique: list[Card] = []
    for card in cards:
        card_base = _vocab_base(vocab_word(card.question))
        card_gap = _gap_key(card.example)
        merged = False
        for existing in unique:
            word = vocab_word(existing.question)
            same_base = _vocab_base(word) == card_base
            same_ctx = bool(card_gap) and _gap_key(existing.example) == card_gap
            if not (same_base or same_ctx):
                continue

            # Keep the spelling that best matches the book's actual word.
            truth = _context_word(existing.example) or _context_word(card.example)
            if _spelling_score(card_base, truth) > _spelling_score(
                    _vocab_base(word), truth):
                existing.question = card.question
                existing.image = card.image
                word = vocab_word(existing.question)

            # Collect distinct contexts (by gapped form) on the answer side,
            # excluding the primary context already shown on the card.
            primary = _gap_key(existing.example)
            seen_keys = {primary} if primary else set()
            all_examples: list[str] = []
            for src in (existing.source_url, card.example, card.source_url):
                for ex in src.split(_SEP):
                    ex = ex.strip()
                    if not ex or len(all_examples) >= max_contexts:
                        continue
                    key = _gap_key(ex)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    all_examples.append(_bold_word_in_context(ex, word))
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
) -> list[Card]:
    """Use LLM to remove duplicate/overlapping cards, keeping the best version."""
    if len(cards) <= 3:
        return cards

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
        response = provider.generate(prompt)
        # Parse the ID list
        match = re.search(r"\[[\d\s,]*]", response.strip())
        if match:
            keep_ids = set(json.loads(match.group(0)))
            kept = [c for i, c in enumerate(cards) if i in keep_ids]
            if kept:
                return kept
    except Exception as e:
        generation_errors.append(f"consolidation skipped: {type(e).__name__}: {str(e)[:200]}")

    return cards
