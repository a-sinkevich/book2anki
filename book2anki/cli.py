import argparse
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from book2anki.models import Card, Chapter
from book2anki.parser_epub import parse_epub
from book2anki.parser_pdf import parse_pdf
from book2anki.parser_web import parse_url
from book2anki.parser_youtube import is_youtube_input, parse_youtube
from book2anki.language import detect_language
from book2anki.generator import (
    LLMProvider, generate_cards_for_chapter, generate_vocab_for_chapter,
    generate_practice_for_chapter, generate_cards_for_prompt,
    deduplicate, deduplicate_vocab,
    consolidate_cards, vocab_word, _vocab_base, PARALLEL_WORKERS,
    generation_errors,
)
from book2anki.anki_reader import read_vocab_words
from book2anki.prompts import detect_programming
from book2anki.diagram_gen import process_book_images
from book2anki.packager import (
    package_cards, package_cards_flat, package_book_flat, package_vocab_flat,
    package_vocab_production, package_practice, package_practice_flat,
    package_practice_chapter,
    package_single_chapter, load_existing_chapters, YOUTUBE_MODEL,
)


def parse_chapters(spec: str) -> list[int]:
    """Parse a chapter spec like '1,3-5,8' into a sorted list of 1-based chapter numbers."""
    result: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"Invalid chapter spec: '{spec}'")
        if "-" in part:
            pieces = part.split("-", 1)
            try:
                start, end = int(pieces[0]), int(pieces[1])
            except ValueError:
                raise ValueError(f"Invalid chapter spec: '{part}'")
            if start < 1 or end < 1:
                raise ValueError(f"Chapter numbers must be >= 1, got '{part}'")
            if start > end:
                raise ValueError(f"Invalid range: {start}-{end}")
            result.update(range(start, end + 1))
        else:
            try:
                num = int(part)
            except ValueError:
                raise ValueError(f"Invalid chapter spec: '{part}'")
            if num < 1:
                raise ValueError(f"Chapter numbers must be >= 1, got {num}")
            result.add(num)
    if not result:
        raise ValueError(f"Invalid chapter spec: '{spec}'")
    return sorted(result)


def _create_provider(model: str | None = None) -> LLMProvider:
    from book2anki.provider_cli import CLIProvider

    shortcuts = {"sonnet", "opus", "cli"}
    gpt_shortcuts = {
        "gpt5.5", "gpt5.4", "gpt5.4-mini", "gpt4o", "gpt4o-mini",
        "o3", "o3-mini", "o4-mini",
    }

    if model == "cli":
        return CLIProvider("opus")

    if model and model.startswith("cli:"):
        cli_model = model.split(":", 1)[1].strip()
        if not cli_model:
            raise ValueError("--model cli:<model> requires a Claude CLI model name")
        return CLIProvider(cli_model)

    if model == "codex":
        from book2anki.provider_codex import CodexCLIProvider
        return CodexCLIProvider()

    # GPT models → OpenAI provider
    if model in gpt_shortcuts or (
        model and model.startswith(("gpt-", "o1", "o3", "o4"))
    ):
        from book2anki.provider_openai import OpenAIProvider
        oai = OpenAIProvider()
        if model:
            oai.set_model(model)
        return oai

    # Shortcut or default: try CLI first, fall back to API
    if model is None or model in shortcuts:
        cli_model = model or "opus"
        if CLIProvider.is_available():
            print(f"Using claude CLI ({cli_model})\n")
            return CLIProvider(cli_model)

    # Exact model ID or CLI unavailable: use API
    from book2anki.provider_claude import ClaudeProvider
    provider = ClaudeProvider()
    if model:
        provider.set_model(model)
    return provider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="book2anki",
        description="Convert nonfiction books (EPUB/PDF) into Anki flashcard decks using LLMs.",
    )
    parser.add_argument(
        "file", nargs="?",
        help="Path to .epub or .pdf file, or a URL (article/YouTube)",
    )
    parser.add_argument(
        "--prompt", default=None,
        help="Generate standalone cards from this study request instead of a source file/url",
    )
    parser.add_argument(
        "--depth", type=int, choices=[0, 1, 2, 3], default=1,
        help="Card generation depth: 0=essential summary, 1=core, 2=detailed, 3=comprehensive (default: 1)",
    )
    parser.add_argument(
        "--lang", default=None,
        help="Card language (default: auto-detect). "
             "Use to generate cards in a different language, e.g. --lang ru",
    )
    parser.add_argument(
        "--topic", default=None,
        help="Generate cards only about a specific topic, e.g. --topic 'dopamine'",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: <BookTitle>/)",
    )
    parser.add_argument(
        "--parallel", action="store_true",
        help="Process chapters in parallel",
    )
    parser.add_argument(
        "--chapters", type=str, default=None,
        help="Chapters to process, e.g. '3', '1,2,5', '3-7', '1,3-5,8' (1-based)",
    )
    parser.add_argument(
        "--vocab", action="store_true",
        help="Vocabulary mode: extract words/phrases above your level for language learning",
    )
    parser.add_argument(
        "--level", default=None,
        choices=["A1", "A2", "B1", "B2", "C1", "C2"],
        help="Your CEFR language level (used with --vocab), e.g. --level B2",
    )
    parser.add_argument(
        "--vocab-mode", default=None,
        choices=["recognition", "production"],
        help="Vocab card direction (used with --vocab): 'production' (default, "
             "meaning → produce the English word, for speaking practice) or "
             "'recognition' (English → meaning)",
    )
    parser.add_argument(
        "--flat", "--compact", action="store_true", dest="flat",
        help="Output a single compact .apkg file instead of per-chapter files",
    )
    parser.add_argument(
        "--practice", action="store_true",
        help="Practice mode: generate programming exercise cards (katas, step-by-step "
             "drills, variations) instead of theory cards. Only for programming books",
    )
    parser.add_argument(
        "--code-lang", default=None,
        help="Programming language for --practice exercises, e.g. --code-lang java",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model to use: sonnet, opus, cli (Claude CLI), codex (Codex CLI), "
             "gpt5.5, gpt5.4, gpt4o, o3, o4-mini, "
             "cli:<model> for exact Claude CLI models, "
             "or any exact API model ID (e.g. claude-opus-5, gpt-5.4-mini)",
    )
    args = parser.parse_args()
    if not args.file and not args.prompt:
        parser.error("file is required unless --prompt is provided")
    if args.file and args.prompt:
        parser.error("--prompt cannot be used together with a file/url")
    if args.prompt and args.chapters:
        parser.error("--chapters only applies to source files/urls")
    if args.prompt and args.topic:
        parser.error("--topic filters a source; put the topic in --prompt instead")
    if args.prompt and args.vocab:
        parser.error("--vocab only applies to source files/urls")
    if args.prompt and args.practice:
        parser.error("--practice only applies to source files/urls")
    if args.prompt and args.code_lang:
        parser.error("--code-lang only applies in practice mode")

    # Checked here rather than after parsing, so a bad flag combination fails
    # before spending a minute extracting text from a large PDF.
    if not args.prompt:
        if args.vocab and not args.level:
            parser.error("--vocab requires --level (e.g. --vocab --level B2)")
        if args.vocab and not args.lang:
            parser.error("--vocab requires --lang to specify your native language "
                         "(e.g. --vocab --level B2 --lang ru)")
        if args.vocab_mode is not None and not args.vocab:
            parser.error("--vocab-mode only applies in vocabulary mode (add --vocab)")
        if args.practice and args.vocab:
            parser.error("--practice and --vocab cannot be used together")
        if args.code_lang and not args.practice:
            parser.error("--code-lang only applies in practice mode (add --practice)")
    if args.vocab_mode is None:
        args.vocab_mode = "production"  # default when --vocab is used
    return args


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _parse_book(filepath: Path) -> tuple[str, list[Chapter]]:
    """Parse an EPUB or PDF file, returning (book_title, chapters)."""
    suffix = filepath.suffix.lower()
    if suffix == ".epub":
        return parse_epub(str(filepath))
    else:
        return parse_pdf(str(filepath))


def _select_chapters(
    chapters: list[Chapter], spec: str | None,
) -> list[Chapter]:
    """Select chapters based on --chapters spec. Returns the subset to process."""
    if spec is None:
        return chapters

    try:
        selected = parse_chapters(spec)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    valid = [n for n in selected if 1 <= n <= len(chapters)]
    skipped = [n for n in selected if n not in valid]

    if not valid:
        print(
            f"Error: chapter(s) {selected} out of range (1-{len(chapters)}).",
            file=sys.stderr,
        )
        sys.exit(1)
    if skipped:
        print(f"Note: skipping out-of-range chapter(s) {skipped} (book has {len(chapters)})")

    names = ", ".join(f'{n}: "{chapters[n - 1].title}"' for n in valid)
    print(f"Selected {len(valid)} chapter(s): {names}")
    return [chapters[n - 1] for n in valid]


_LANG_NAMES: dict[str, dict[str, str]] = {
    "en": {"en": "English", "ru": "Английский", "de": "Englisch", "fr": "Anglais",
           "es": "Inglés", "it": "Inglese", "pt": "Inglês", "zh": "英语", "ja": "英語", "ko": "영어"},
    "ru": {"en": "Russian", "ru": "Русский", "de": "Russisch", "fr": "Russe", "es": "Ruso"},
    "de": {"en": "German", "ru": "Немецкий", "de": "Deutsch", "fr": "Allemand", "es": "Alemán"},
    "fr": {"en": "French", "ru": "Французский", "de": "Französisch", "fr": "Français", "es": "Francés"},
    "es": {"en": "Spanish", "ru": "Испанский", "de": "Spanisch", "fr": "Espagnol", "es": "Español"},
    "it": {"en": "Italian", "ru": "Итальянский", "de": "Italienisch", "fr": "Italien", "es": "Italiano"},
    "pt": {"en": "Portuguese", "ru": "Португальский"},
    "zh": {"en": "Chinese", "ru": "Китайский"},
    "ja": {"en": "Japanese", "ru": "Японский"},
    "ko": {"en": "Korean", "ru": "Корейский"},
    "no": {"en": "Norwegian", "ru": "Норвежский", "no": "Norsk"},
    "nb": {"en": "Norwegian", "ru": "Норвежский", "nb": "Norsk"},
    "sv": {"en": "Swedish", "ru": "Шведский", "sv": "Svenska"},
    "da": {"en": "Danish", "ru": "Датский", "da": "Dansk"},
    "nl": {"en": "Dutch", "ru": "Нидерландский", "nl": "Nederlands"},
    "pl": {"en": "Polish", "ru": "Польский", "pl": "Polski"},
    "tr": {"en": "Turkish", "ru": "Турецкий", "tr": "Türkçe"},
    "ar": {"en": "Arabic", "ru": "Арабский"},
    "he": {"en": "Hebrew", "ru": "Иврит"},
    "uk": {"en": "Ukrainian", "ru": "Украинский", "uk": "Українська"},
    "cs": {"en": "Czech", "ru": "Чешский", "cs": "Čeština"},
    "fi": {"en": "Finnish", "ru": "Финский", "fi": "Suomi"},
}


def _lang_name(source_lang: str) -> str:
    """Get the name of a language in that language itself."""
    names = _LANG_NAMES.get(source_lang, {})
    return names.get(source_lang) or names.get("en") or source_lang.upper()


_MAX_TOPIC_LEN = 25
_MAX_PROMPT_TITLE_LEN = 80


def _safe_name(title: str) -> str:
    """Turn a deck title into a filesystem-safe base name."""
    return re.sub(r'[<>:"/\\|?*]', "", title).replace(" ", "_")


def _short_topic(topic: str) -> str:
    """Truncate topic for display in deck/file names."""
    if len(topic) <= _MAX_TOPIC_LEN:
        return topic
    return topic[:_MAX_TOPIC_LEN].rsplit(" ", 1)[0] + "…"


def _prompt_deck_title(request: str) -> str:
    """Build a readable deck title from a source-free study request."""
    title = re.sub(r"\s+", " ", request).strip()
    if len(title) > _MAX_PROMPT_TITLE_LEN:
        title = title[:_MAX_PROMPT_TITLE_LEN].rsplit(" ", 1)[0] + "…"
    return f"Prompt — {title or 'Study Request'}"


def _base_name(title: str, depth: int) -> str:
    """Filesystem-safe stem for a deck, tagged with a non-default depth."""
    safe = _safe_name(title)
    return f"{safe}_d{depth}" if depth != 1 else safe


def _apkg_output_path(base_title: str, output: str | None, depth: int = 1) -> str:
    """Build an .apkg output path from a title and optional file/directory output."""
    safe = _base_name(base_title, depth)
    if not output:
        return f"{safe}.apkg"
    if output.endswith(".apkg"):
        return output
    return str(Path(output) / f"{safe}.apkg")


def _deck_title(book_title: str, topic: str | None) -> str:
    """Build deck title, appending truncated topic if specified."""
    if not topic:
        return book_title
    return f"{book_title} — {_short_topic(topic)}"


def _use_single_deck(topic: str | None, flat: bool) -> bool:
    """Return whether book output should be a single compact deck."""
    return bool(topic) or flat


def _chapter_order(chapters: list[Chapter]) -> dict[str, int]:
    """Map chapter titles to their original zero-based book index."""
    return {chapter.title: chapter.index for chapter in chapters}


def _cleanup_media(media_files: list[str]) -> None:
    """Remove temporary media files and their parent dir if empty."""
    dirs: set[str] = set()
    for path in media_files:
        dirs.add(os.path.dirname(path))
        try:
            os.remove(path)
        except OSError:
            pass
    for d in dirs:
        try:
            os.rmdir(d)  # only removes if empty
        except OSError:
            pass


@dataclass
class _Source:
    """Everything the modes need to know about the parsed input."""
    title: str
    chapters: list[Chapter]   # the selected subset, in book order
    lang: str
    is_url: bool
    is_youtube: bool
    is_programming: bool
    url: str = ""

    @property
    def is_single(self) -> bool:
        """Articles and videos are one chapter with no per-chapter output."""
        return self.is_url or self.is_youtube


def _resume_existing(
    chapters_dir: str, chapters: list[Chapter],
) -> tuple[dict[int, list[Card]], list[Card]]:
    """Load already-generated chapters so a re-run picks up where it stopped.

    Returns the per-index map of everything on disk and the cards belonging to
    chapters that are in scope for this run.
    """
    if not chapters_dir:
        return {}, []

    existing = load_existing_chapters(chapters_dir)
    in_scope = {ch.index for ch in chapters}
    cards = [
        card for idx in sorted(existing)
        if idx in in_scope
        for card in existing[idx]
    ]
    done = in_scope & existing.keys()
    if done:
        print(f"Resuming: {len(done)}/{len(chapters)} chapters already done"
              f" ({len(cards)} cards)")
    return existing, cards


def _dedup_similar(cards: list[Card]) -> list[Card]:
    """Drop near-duplicate cards, reporting how many went."""
    before = len(cards)
    cards = deduplicate(cards)
    if len(cards) < before:
        print(f"Removed {before - len(cards)} similar cards"
              f" ({before} → {len(cards)})")
    return cards


def _run_prompt_mode(args: argparse.Namespace) -> None:
    """Generate a flat deck from a source-free study request."""
    request = args.prompt.strip()
    if not request:
        print("Error: --prompt cannot be empty", file=sys.stderr)
        sys.exit(1)

    fallback_title = _prompt_deck_title(request)
    lang = detect_language(request, override=args.lang)

    print(f'"{fallback_title}"')
    print(f"Mode: prompt study guide, depth={args.depth}"
          f"{', lang=' + args.lang if args.lang else ', lang=auto'}")
    print(f"Language: {lang}")
    print()

    provider = _make_provider(args)
    model = provider.model_name()

    print("Generating...")
    deck_title, cards = generate_cards_for_prompt(
        provider, request, fallback_title, args.depth, lang,
        status_fn=lambda msg: print(msg, flush=True),
    )

    if not cards:
        _print_generation_errors()
        print("Error: No cards were generated.", file=sys.stderr)
        sys.exit(1)

    output_path = _apkg_output_path(deck_title, args.output, args.depth)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    package_cards_flat(
        cards, deck_title, output_path,
        tag_prefix="prompt", model_version=model,
    )

    if deck_title != fallback_title:
        print(f"Deck title: {deck_title}")
    print(f"\nDone! Generated {len(cards)} cards.")
    print(f"Output: {output_path}\n")


def _make_provider(args: argparse.Namespace) -> LLMProvider:
    """Build the LLM provider and announce which model will be used."""
    try:
        provider = _create_provider(args.model)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Cards model: {provider.model_name()}")
    print()
    return provider


def _parse_source(args: argparse.Namespace) -> _Source:
    """Parse the input file/URL and pick the chapters to process."""
    is_url = _is_url(args.file)
    is_yt = is_youtube_input(args.file)

    try:
        if is_yt:
            book_title, chapters = parse_youtube(args.file)
        elif is_url:
            book_title, chapters = parse_url(args.file)
        else:
            filepath = Path(args.file)
            if not filepath.exists():
                print(f"Error: File not found: {filepath}", file=sys.stderr)
                sys.exit(1)
            suffix = filepath.suffix.lower()
            if suffix not in (".epub", ".pdf"):
                print(f"Error: Unsupported file format '{suffix}'. Use .epub or .pdf.",
                      file=sys.stderr)
                sys.exit(1)
            book_title, chapters = _parse_book(filepath)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not chapters:
        print("Error: No content could be extracted.", file=sys.stderr)
        sys.exit(1)

    if is_url or is_yt:
        print(f'"{book_title}"')
    else:
        print(f'"{book_title}" — {len(chapters)} chapter(s) extracted.')
    _print_mode_line(args)

    selected = _select_chapters(chapters, args.chapters)
    all_text = "\n".join(ch.text for ch in selected)
    lang = detect_language(all_text, override=args.lang)
    is_prog = detect_programming(all_text)

    print(f"Language: {lang}")
    if is_prog:
        print("Content: programming (code-aware cards)")
    images = len({img.id for ch in selected for img in ch.images})
    if images:
        label = "Images" if (is_url or is_yt) else "Book images"
        print(f"{label}: {images} figures extracted")
    print()

    url = ""
    if is_yt:
        url = f"https://www.youtube.com/watch?v={args.file}"
    elif is_url:
        url = args.file

    return _Source(
        title=book_title, chapters=selected, lang=lang,
        is_url=is_url, is_youtube=is_yt, is_programming=is_prog, url=url,
    )


def _print_mode_line(args: argparse.Namespace) -> None:
    """Echo the effective run parameters."""
    chapters = ', chapters=' + args.chapters if args.chapters else ', chapters=all'
    topic = ', topic=' + args.topic if args.topic else ''
    if args.vocab:
        print(f"Mode: vocabulary extraction (level {args.level})"
              f", cards={args.vocab_mode}{chapters}"
              f"{', lang=' + args.lang if args.lang else ', lang=auto'}{topic}")
    elif args.practice:
        print(f"Mode: practice exercises, depth={args.depth}{chapters}"
              f"{', code-lang=' + args.code_lang if args.code_lang else ''}{topic}"
              f"{', parallel' if args.parallel else ''}")
    else:
        print(f"Parameters: depth={args.depth}{chapters}"
              f"{', lang=' + args.lang if args.lang else ', lang=auto'}{topic}"
              f"{', parallel' if args.parallel else ''}")


def main() -> None:
    from book2anki.envfile import load_env
    load_env()

    args = _parse_args()

    if args.prompt:
        _run_prompt_mode(args)
        return

    source = _parse_source(args)
    provider = _make_provider(args)

    if args.practice:
        _run_practice_mode(args, source, provider)
    elif args.vocab:
        _run_vocab_mode(args, source, provider)
    elif source.is_single:
        _run_single_source_mode(args, source, provider)
    else:
        _run_book_mode(args, source, provider)


def _run_practice_mode(
    args: argparse.Namespace, source: _Source, provider: LLMProvider,
) -> None:
    """Generate programming exercise cards."""
    if not source.is_programming:
        print("Warning: book does not appear to be about programming. "
              "Practice mode works best with programming books.",
              file=sys.stderr)

    model = provider.model_name()
    deck_title = _deck_title(source.title, args.topic)
    if args.code_lang:
        deck_title = f"Practice | {args.code_lang.capitalize()} | {deck_title}"
    else:
        deck_title = f"Practice | {deck_title}"

    def run(chapter: Chapter, bar: Any = None, on_chunk: Any = None) -> list[Card]:
        return generate_practice_for_chapter(
            provider, chapter, source.title,
            depth=args.depth,
            progress_bar=bar,
            topic=args.topic or "",
            code_lang=args.code_lang or "",
            on_chunk_done=on_chunk,
            parallel_chunks=args.parallel,
        )

    if source.is_single:
        cards = _process_single_source(
            lambda bar, on_chunk: run(source.chapters[0], bar, on_chunk),
        )
        if not cards:
            _fail_no_cards("practice cards")
        output_path = args.output or f"{_safe_name(deck_title)}.apkg"
        package_practice_flat(cards, deck_title, output_path, model_version=model)
        print(f"\nDone! Generated {len(cards)} practice cards.")
        print(f"Output: {output_path}\n")
        return

    base_name = _base_name(deck_title, args.depth)
    output_dir = args.output or base_name
    single_deck = args.flat
    chapters_dir = "" if single_deck else str(Path(output_dir) / "chapters")

    existing, all_cards = _resume_existing(chapters_dir, source.chapters)
    pending = [ch for ch in source.chapters if ch.index not in existing]

    def save(chapter: Chapter, cards: list[Card]) -> None:
        if chapters_dir:
            package_practice_chapter(
                cards, deck_title, chapter.index, chapters_dir,
                model_version=model,
            )

    if pending:
        all_cards += _process_chapters(
            pending, run, args.parallel, on_done=save,
            all_chapters=source.chapters,
            existing_counts={idx: len(c) for idx, c in existing.items()} or None,
        )

    if not all_cards:
        _fail_no_cards("practice cards")

    if single_deck and len(all_cards) > 3:
        all_cards = _dedup_similar(all_cards)

    if single_deck:
        package_practice_flat(
            all_cards, deck_title, f"{output_dir}.apkg", model_version=model,
        )
    else:
        os.makedirs(output_dir, exist_ok=True)
        combined = str(Path(output_dir) / f"{base_name}.apkg")
        package_practice(
            all_cards, deck_title, combined, model_version=model,
            chapter_order=_chapter_order(source.chapters),
        )

    print(f"\nDone! Generated {len(all_cards)} practice cards.")
    print(f"Output: {output_dir}.apkg\n" if single_deck else f"Output: {output_dir}/\n")


def _run_vocab_mode(
    args: argparse.Namespace, source: _Source, provider: LLMProvider,
) -> None:
    """Extract vocabulary above the learner's level into a flat deck."""
    # Source language is always the book's own; --lang is the translation target.
    source_lang = detect_language("\n".join(ch.text for ch in source.chapters))
    model = provider.model_name()

    # Check Anki for existing vocab words to skip (normalized base forms)
    existing_raw = read_vocab_words()
    existing_words = {_vocab_base(w) for w in existing_raw}
    if existing_words:
        print(f"Existing Anki collection: {len(existing_raw)} vocab words found, "
              "will skip duplicates")

    def run(chapter: Chapter, bar: Any = None, on_chunk: Any = None) -> list[Card]:
        return generate_vocab_for_chapter(
            provider, chapter, source.title,
            level=args.level, native_language=args.lang,
            progress_bar=bar,
            is_article=source.is_single,
            topic=args.topic or "",
            on_chunk_done=on_chunk,
            parallel_chunks=args.parallel,
        )

    if source.is_single:
        all_cards = _process_single_source(
            lambda bar, on_chunk: run(source.chapters[0], bar, on_chunk),
        )
    else:
        all_cards = _process_chapters(source.chapters, run, args.parallel)

    if not all_cards:
        _fail_no_cards("vocabulary cards")

    # Merge duplicates across chapters (same word may appear in multiple chapters)
    before = len(all_cards)
    all_cards = deduplicate_vocab(all_cards)
    if len(all_cards) < before:
        print(f"Merged {before - len(all_cards)} duplicate words"
              f" ({before} → {len(all_cards)})")

    if existing_words:
        before = len(all_cards)
        all_cards = [
            c for c in all_cards
            if _vocab_base(vocab_word(c.question)) not in existing_words
        ]
        if len(all_cards) < before:
            print(f"Skipped {before - len(all_cards)} words already in Anki"
                  f" ({before} → {len(all_cards)})")

    deck_parts = [f"{_lang_name(source_lang)} {args.level}", source.title]
    if args.topic:
        deck_parts.append(_short_topic(args.topic))
    deck_title = " — ".join(deck_parts)

    file_parts = list(deck_parts)
    if args.chapters:
        file_parts.append(f"ch.{args.chapters}")
    base_name = _safe_name(" — ".join(file_parts))

    output_path = args.output or f"{base_name}.apkg"
    if not output_path.endswith(".apkg"):
        output_path = str(Path(output_path) / f"{base_name}.apkg")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    package = (
        package_vocab_production if args.vocab_mode == "production"
        else package_vocab_flat
    )
    package(all_cards, deck_title, output_path, model_version=model)

    print(f"\nDone! Generated {len(all_cards)} vocabulary cards.")
    print(f"Output: {output_path}\n")


def _run_single_source_mode(
    args: argparse.Namespace, source: _Source, provider: LLMProvider,
) -> None:
    """Generate a flat deck from a web article or YouTube transcript."""
    model = provider.model_name()
    deck_title = _deck_title(source.title, args.topic)

    cards = _process_single_source(
        lambda bar, on_chunk: generate_cards_for_chapter(
            provider=provider,
            chapter=source.chapters[0],
            book_title=source.title,
            depth=args.depth,
            language=source.lang,
            progress_bar=bar,
            is_article=True,
            source_url=source.url,
            is_programming=source.is_programming,
            topic=args.topic or "",
            on_chunk_done=on_chunk,
            parallel_chunks=args.parallel,
            is_transcript=source.is_youtube,
        ),
    )
    if not cards:
        _fail_no_cards("cards")

    media: list[str] = []
    if source.chapters[0].images:
        media = process_book_images(cards, source.chapters[0].images, "media")

    path = f"{args.output or _base_name(deck_title, args.depth)}.apkg"
    if source.is_youtube:
        package_cards_flat(
            cards, deck_title, path, tag_prefix="youtube", model=YOUTUBE_MODEL,
            media_files=media, model_version=model,
        )
    else:
        package_cards_flat(
            cards, deck_title, path, media_files=media, model_version=model,
        )

    # Clean up temporary media files (already embedded in .apkg)
    _cleanup_media(media)

    print(f"\nDone! Generated {len(cards)} cards.")
    print(f"Output: {path}\n")


def _run_book_mode(
    args: argparse.Namespace, source: _Source, provider: LLMProvider,
) -> None:
    """Generate per-chapter decks (or one compact deck) from a book."""
    model = provider.model_name()
    deck_title = _deck_title(source.title, args.topic)
    output_dir = args.output or _base_name(source.title, args.depth)
    single_deck = _use_single_deck(args.topic, args.flat)
    chapters_dir = "" if single_deck else str(Path(output_dir) / "chapters")

    existing, all_cards = _resume_existing(chapters_dir, source.chapters)
    pending = [ch for ch in source.chapters if ch.index not in existing]
    media: list[str] = []

    def run(chapter: Chapter, bar: Any = None, on_chunk: Any = None) -> list[Card]:
        return generate_cards_for_chapter(
            provider=provider,
            chapter=chapter,
            book_title=source.title,
            depth=args.depth,
            language=source.lang,
            progress_bar=bar,
            is_programming=source.is_programming,
            topic=args.topic or "",
            on_chunk_done=on_chunk,
            parallel_chunks=args.parallel,
        )

    def save(chapter: Chapter, cards: list[Card]) -> None:
        chapter_media: list[str] = []
        if chapter.images:
            chapter_media = process_book_images(
                cards, chapter.images, os.path.join(chapters_dir or ".", "media"),
            )
            media.extend(chapter_media)
        if chapters_dir:
            package_single_chapter(
                cards, source.title, chapter.index, chapters_dir,
                media_files=chapter_media, model_version=model,
            )

    if pending:
        all_cards += _process_chapters(
            pending, run, args.parallel, on_done=save,
            all_chapters=source.chapters,
            existing_counts={idx: len(c) for idx, c in existing.items()} or None,
        )

    if not all_cards:
        _fail_no_cards("cards")

    # Cross-chapter dedup for compact/topic mode
    if single_deck and len(all_cards) > 3:
        all_cards = _dedup_similar(all_cards)
        # LLM consolidation — pick best among near-duplicates
        if args.depth == 0 or args.topic:
            print("Consolidating cards...")
            all_cards = consolidate_cards(provider, all_cards, source.lang)
            print(f"Final: {len(all_cards)} cards")

    if single_deck:
        package_book_flat(
            all_cards, deck_title, f"{output_dir}.apkg",
            media_files=media, model_version=model,
        )
    else:
        os.makedirs(output_dir, exist_ok=True)
        combined = str(Path(output_dir) / f"{_safe_name(source.title)}.apkg")
        package_cards(
            all_cards, deck_title, combined, media_files=media,
            model_version=model, chapter_order=_chapter_order(source.chapters),
        )

    # Clean up temporary media files (already embedded in .apkg)
    _cleanup_media(media)

    print(f"\nDone! Generated {len(all_cards)} cards "
          f"across {len(source.chapters)} chapter(s).")
    print(f"Output: {output_dir}.apkg\n" if single_deck else f"Output: {output_dir}/\n")


def _fail_no_cards(what: str) -> None:
    """Report generation failures and exit."""
    _print_generation_errors()
    print(f"Error: No {what} were generated.", file=sys.stderr)
    sys.exit(1)


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s"


def _fmt_mm_ss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


class _ProgressBar:
    """Progress bar that stays at top, with content printed below."""

    def __init__(self, total: int, initial: int = 0):
        self.n = initial
        self.total = total
        self._start = time.monotonic()
        self._postfix = ""
        self._lines_below = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._out = sys.stderr
        try:
            self._cols = os.get_terminal_size(self._out.fileno()).columns
        except (OSError, ValueError):
            self._cols = 120
        self._out.write(self._format()[:self._cols] + "\n")
        self._out.flush()
        t = threading.Thread(target=self._tick, daemon=True)
        t.start()

    def _tick(self) -> None:
        while not self._stop.wait(1.0):
            self.refresh()

    def _format(self) -> str:
        width = 20
        frac = self.n / self.total if self.total else 0
        filled = int(width * frac)
        bar = "█" * filled + "░" * (width - filled)
        elapsed = time.monotonic() - self._start
        elapsed_s = _fmt_mm_ss(elapsed)
        if 0 < self.n < self.total:
            remain_s = "~" + _fmt_mm_ss(elapsed * (self.total - self.n) / self.n)
        else:
            remain_s = "~00:00"
        postfix = f" {self._postfix}" if self._postfix else ""
        label = "chapters" if self.total > 1 else ""
        count = f" {self.n}/{self.total} {label}," if self.total > 1 else ""
        return (
            f"Generating: {bar}{count} "
            f"elapsed: {elapsed_s}, remaining: {remain_s}{postfix}"
        )

    def _redraw(self) -> None:
        up = self._lines_below + 1
        line = self._format()[:self._cols]
        self._out.write(
            f"\033[{up}A"  # move up to bar line
            f"\r\033[K"    # go to col 0, clear line
            f"{line}"      # write bar (truncated to terminal width)
            f"\033[{up}B"  # move back down
            f"\r"          # go to col 0
        )
        self._out.flush()

    def refresh(self) -> None:
        with self._lock:
            self._redraw()

    def set_postfix_str(self, s: str, refresh: bool = True) -> None:
        with self._lock:
            self._postfix = s
            if refresh:
                self._redraw()

    def update(self, n: int = 1) -> None:
        with self._lock:
            self.n += n
            self._redraw()

    def write(self, text: str) -> None:
        """Print a line below the bar."""
        with self._lock:
            self._out.write(f"\r\033[K{text}\n")
            self._lines_below += 1
            self._redraw()

    def close(self) -> None:
        """Stop refresh thread and finalize bar position."""
        self._stop.set()
        with self._lock:
            self._redraw()
            self._out.write("\n")
            self._out.flush()


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_TBL_HEADER = f"{'Chapter':<45} {'Cards':>5}  {'Time':>7}"
_TBL_SEP = "-" * 45 + " " + "-" * 5 + "  " + "-" * 7


def _tbl_row(title: str, cards: str, time_s: str) -> str:
    short = title[:43] + "…" if len(title) > 44 else title
    return f"{short:<45} {cards:>5}  {time_s:>7}"


class _ChapterProgress:
    """Live table showing all chapters with in-place updates."""

    def __init__(
        self, chapters: list[Chapter],
        existing: dict[int, int] | None = None,
    ):
        self._chapters = chapters
        self._n = len(chapters)
        self._pos = {ch.index: i for i, ch in enumerate(chapters)}
        self._out = sys.stderr
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._spin = 0
        # +2 for header + separator
        self._total_lines = self._n + 2

        self._state: list[str] = []
        self._cards: list[int] = [0] * self._n
        self._elapsed: list[float] = [0.0] * self._n
        self._ch_start: list[float] = [0.0] * self._n

        for ch in chapters:
            if existing and ch.index in existing:
                self._state.append("cached")
                pos = self._pos[ch.index]
                self._cards[pos] = existing[ch.index]
            else:
                self._state.append("pending")

        try:
            self._cols = os.get_terminal_size(self._out.fileno()).columns
        except (OSError, ValueError):
            self._cols = 120

        self._out.write(_TBL_HEADER + "\n" + _TBL_SEP + "\n")
        for i in range(self._n):
            self._out.write(self._fmt(i) + "\n")
        self._out.flush()
        threading.Thread(target=self._tick_loop, daemon=True).start()

    def _tick_loop(self) -> None:
        while not self._stop.wait(0.15):
            with self._lock:
                self._spin = (self._spin + 1) % len(_SPINNER)
                for i in range(self._n):
                    if self._state[i] == "active":
                        self._redraw(i)

    def _fmt(self, i: int) -> str:
        st = self._state[i]
        title = self._chapters[i].title
        if st == "done":
            return _tbl_row(
                title, str(self._cards[i]),
                _fmt_elapsed(self._elapsed[i]),
            )
        if st == "cached":
            return _tbl_row(title, str(self._cards[i]), "—")
        if st == "active":
            s = _SPINNER[self._spin]
            elapsed = time.monotonic() - self._ch_start[i]
            return _tbl_row(title, s, _fmt_elapsed(elapsed))
        # pending
        return _tbl_row(title, "", "")

    def _redraw(self, i: int) -> None:
        up = self._n - i
        line = self._fmt(i)[:self._cols]
        self._out.write(f"\033[{up}A\r\033[K{line}\033[{up}B\r")
        self._out.flush()

    def start_chapter(self, chapter_index: int) -> None:
        with self._lock:
            pos = self._pos.get(chapter_index)
            if pos is not None:
                self._state[pos] = "active"
                self._ch_start[pos] = time.monotonic()
                self._redraw(pos)

    def complete_chapter(
        self, chapter_index: int, cards: int, elapsed: float,
    ) -> None:
        with self._lock:
            pos = self._pos.get(chapter_index)
            if pos is not None:
                self._state[pos] = "done"
                self._cards[pos] = cards
                self._elapsed[pos] = elapsed
                self._redraw(pos)

    # ProgressBar-compatible interface for generator callbacks
    def set_postfix_str(self, s: str, refresh: bool = True) -> None:
        pass

    def write(self, text: str) -> None:
        pass

    def update(self, n: int = 1) -> None:
        pass

    def refresh(self) -> None:
        pass

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            for i in range(self._n):
                if self._state[i] == "active":
                    self._redraw(i)
        self._out.write("\n")
        self._out.flush()


def _print_summary(
    total_cards: int, total_time: float,
    cached_cards: int = 0,
) -> None:
    print(
        _TBL_SEP + "\n" +
        _tbl_row("Total", str(total_cards + cached_cards), _fmt_elapsed(total_time)),
        file=sys.stderr,
    )
    _print_generation_errors()


def _print_generation_errors() -> None:
    """Report failures collected while the live table owned the terminal."""
    if not generation_errors:
        return
    print("\nProblems during generation:", file=sys.stderr)
    for err in generation_errors:
        print(f"  ✗ {err}", file=sys.stderr)
    generation_errors.clear()


class _QuietBar:
    """No-op progress bar to suppress per-chunk status in parallel mode."""

    def set_postfix_str(self, msg: str, refresh: bool = False) -> None:
        pass


ChunkCallback = Callable[[int, int], None]
SingleSourceRun = Callable[[Any, ChunkCallback], list[Card]]
ChapterRun = Callable[[Chapter, Any, ChunkCallback | None], list[Card]]


def _process_single_source(generate: SingleSourceRun) -> list[Card]:
    """Generate cards for a one-chapter source (article/video), tracking chunks.

    The bar starts as a single unit and rescales itself the moment the
    generator reports how many chunks the text actually split into.
    """
    pbar = _ProgressBar(total=1)

    def on_chunk_done(done: int, total: int) -> None:
        if done == 0:
            pbar.total = total
            pbar.n = 0
        else:
            pbar.n = done
        pbar.refresh()

    try:
        return generate(pbar, on_chunk_done)
    finally:
        pbar.close()
        _print_generation_errors()


def _process_chapters(
    chapters: list[Chapter],
    run: ChapterRun,
    parallel: bool,
    on_done: Callable[[Chapter, list[Card]], None] | None = None,
    all_chapters: list[Chapter] | None = None,
    existing_counts: dict[int, int] | None = None,
) -> list[Card]:
    """Generate cards chapter by chapter behind the live progress table.

    Returns this run's new cards in book order. `on_done` fires on the calling
    thread as each chapter lands, so it can write that chapter's .apkg and let
    an interrupted run resume. Failures go to `generation_errors` rather than
    stderr, which the table owns until it closes.
    """
    cp = _ChapterProgress(all_chapters or chapters, existing=existing_counts)
    quiet = _QuietBar()
    cards_by_chapter: dict[int, list[Card]] = {}
    started: dict[int, float] = {}
    wall_start = time.monotonic()

    def start(chapter: Chapter) -> list[Card]:
        cp.start_chapter(chapter.index)
        started[chapter.index] = time.monotonic()
        return run(chapter, quiet, None)

    def collect(chapter: Chapter, cards: list[Card]) -> None:
        cards_by_chapter[chapter.index] = cards
        if cards and on_done:
            on_done(chapter, cards)

    def complete(chapter: Chapter) -> None:
        cp.complete_chapter(
            chapter.index,
            len(cards_by_chapter.get(chapter.index, [])),
            time.monotonic() - started.get(chapter.index, wall_start),
        )

    if parallel:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = {executor.submit(start, ch): ch for ch in chapters}
            for future in as_completed(futures):
                chapter = futures[future]
                try:
                    collect(chapter, future.result())
                except Exception as e:
                    generation_errors.append(
                        f'"{chapter.title}": {type(e).__name__}: {str(e)[:300]}'
                    )
                complete(chapter)
    else:
        for chapter in chapters:
            collect(chapter, start(chapter))
            complete(chapter)

    cp.close()
    _print_summary(
        sum(len(c) for c in cards_by_chapter.values()),
        time.monotonic() - wall_start,
        cached_cards=sum(existing_counts.values()) if existing_counts else 0,
    )
    return [card for idx in sorted(cards_by_chapter) for card in cards_by_chapter[idx]]


if __name__ == "__main__":
    main()
