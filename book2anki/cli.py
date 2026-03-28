import argparse
import os
import re
import sys
import threading
import time
from pathlib import Path

from book2anki.models import Card, Chapter, TokenUsage
from book2anki.parser_epub import parse_epub
from book2anki.parser_pdf import parse_pdf
from book2anki.parser_web import parse_url
from book2anki.parser_youtube import is_youtube_input, parse_youtube
from book2anki.language import detect_language
from book2anki.generator import (
    LLMProvider, generate_cards_for_chapter, generate_vocab_for_chapter,
    estimate_cost, format_cost, deduplicate, deduplicate_vocab,
    consolidate_cards, vocab_word, _vocab_base,
)
from book2anki.anki_reader import read_vocab_words
from book2anki.prompts import detect_programming
from book2anki.diagram_gen import process_book_images
from book2anki.packager import (
    package_cards, package_cards_flat, package_book_flat, package_vocab_flat,
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

    if model == "cli":
        return CLIProvider("opus")

    # Default or explicit model: try CLI first, fall back to API
    cli_model = model or "opus"
    if CLIProvider.is_available():
        print(f"Using claude CLI ({cli_model})\n")
        return CLIProvider(cli_model)

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
    parser.add_argument("file", help="Path to .epub or .pdf file, or a URL (article/YouTube)")
    parser.add_argument(
        "--depth", type=int, choices=[0, 1, 2, 3], default=1,
        help="Card generation depth: 0=summary (2-3 cards), 1=core, 2=detailed, 3=comprehensive (default: 1)",
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
        "--flat", action="store_true",
        help="Output a single .apkg file instead of per-chapter files",
    )
    parser.add_argument(
        "--model", default=None,
        choices=["sonnet", "opus", "cli"],
        help="Model to use: sonnet (default), opus (~15x cost), cli (use claude CLI)",
    )
    return parser.parse_args()


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


def _short_topic(topic: str) -> str:
    """Truncate topic for display in deck/file names."""
    if len(topic) <= _MAX_TOPIC_LEN:
        return topic
    return topic[:_MAX_TOPIC_LEN].rsplit(" ", 1)[0] + "…"


def _deck_title(book_title: str, topic: str | None) -> str:
    """Build deck title, appending truncated topic if specified."""
    if not topic:
        return book_title
    return f"{book_title} — {_short_topic(topic)}"


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


def _write_single_output(
    all_cards: list[Card], book_title: str, output: str | None,
    is_youtube: bool = False, media_files: list[str] | None = None,
    depth: int = 1,
) -> str:
    """Write a single .apkg file for a URL source. Returns output path."""
    base_name = output or re.sub(r'[<>:"/\\|?*]', "", book_title).replace(" ", "_")
    if not output and depth != 1:
        base_name = f"{base_name}_d{depth}"
    path = f"{base_name}.apkg"
    if is_youtube:
        package_cards_flat(
            all_cards, book_title, path,
            tag_prefix="youtube", model=YOUTUBE_MODEL,
            media_files=media_files,
        )
    else:
        package_cards_flat(all_cards, book_title, path, media_files=media_files)
    return base_name


def _write_output(
    all_cards: list[Card],
    book_title: str,
    output_dir: str,
    full_book: bool,
    flat: bool = False,
    media_files: list[str] | None = None,
) -> None:
    """Write final Anki deck output files."""
    if flat:
        # Single flat deck — write .apkg directly, no folder needed
        path = f"{output_dir}.apkg"
        package_book_flat(all_cards, book_title, path, media_files=media_files)
    elif full_book:
        os.makedirs(output_dir, exist_ok=True)
        base_name = re.sub(r'[<>:"/\\|?*]', "", book_title).replace(" ", "_")
        combined_path = str(Path(output_dir) / f"{base_name}.apkg")
        package_cards(all_cards, book_title, combined_path, media_files=media_files)


def main() -> None:
    from book2anki.envfile import load_env
    load_env()

    args = _parse_args()

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
                print(f"Error: Unsupported file format '{suffix}'. Use .epub or .pdf.", file=sys.stderr)
                sys.exit(1)
            book_title, chapters = _parse_book(filepath)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not chapters:
        print("Error: No content could be extracted.", file=sys.stderr)
        sys.exit(1)

    if args.vocab and not args.level:
        print("Error: --vocab requires --level (e.g. --vocab --level B2)", file=sys.stderr)
        sys.exit(1)
    if args.vocab and not args.lang:
        print("Error: --vocab requires --lang to specify your native language "
              "(e.g. --vocab --level B2 --lang ru)", file=sys.stderr)
        sys.exit(1)

    if is_url or is_yt:
        print(f'"{book_title}"')
    else:
        print(f'"{book_title}" — {len(chapters)} chapter(s) extracted.')
    if args.vocab:
        print(f"Mode: vocabulary extraction (level {args.level})"
              f"{', chapters=' + args.chapters if args.chapters else ', chapters=all'}"
              f"{', lang=' + args.lang if args.lang else ', lang=auto'}"
              f"{', topic=' + args.topic if args.topic else ''}")
    else:
        print(f"Parameters: depth={args.depth}"
              f"{', chapters=' + args.chapters if args.chapters else ', chapters=all'}"
              f"{', lang=' + args.lang if args.lang else ', lang=auto'}"
              f"{', topic=' + args.topic if args.topic else ''}"
              f"{', parallel' if args.parallel else ''}")

    chapters_to_generate = _select_chapters(chapters, args.chapters)

    all_text = "\n".join(ch.text for ch in chapters_to_generate)
    lang = detect_language(all_text, override=args.lang)
    is_prog = detect_programming(all_text)
    total_book_images = len({img.id for ch in chapters_to_generate for img in ch.images})
    print(f"Language: {lang}")
    if is_prog:
        print("Content: programming (code-aware cards)")
    if total_book_images:
        label = "Images" if is_url or is_yt else "Book images"
        print(f"{label}: {total_book_images} figures extracted")
    print()

    try:
        provider = _create_provider(args.model)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    model_name = provider.model_name()
    print(f"Cards model: {model_name}")
    if "opus" in model_name:
        print("\033[38;5;208m⚠  Opus uses ~5x more tokens than Sonnet. "
              "Use --model sonnet to reduce usage.\033[0m")
    print()

    all_cards: list[Card] = []
    all_media: list[str] = []

    total_usage = TokenUsage(0, 0)
    model = provider.model_name()
    deck_title = _deck_title(book_title, args.topic)

    if args.vocab:
        # In vocab mode: source language = book's language (auto-detected),
        # native language = --lang override (translation target)
        source_lang = detect_language(all_text)  # always auto-detect
        native_lang = args.lang

        # Check Anki for existing vocab words to skip (normalized base forms)
        existing_raw = read_vocab_words()
        existing_words = {_vocab_base(w) for w in existing_raw}
        if existing_words:
            print(f"Existing Anki collection: {len(existing_raw)} vocab words found, "
                  "will skip duplicates")

        total = len(chapters_to_generate)
        if args.parallel and total > 1:
            all_cards, total_usage = _process_vocab_parallel(
                provider, chapters_to_generate, book_title,
                level=args.level, native_language=native_lang,
                total=total, is_article=(is_url or is_yt),
                topic=args.topic or "",
            )
        else:
            is_single = (is_url or is_yt)
            is_book_vocab = not is_single and total > 1

            if is_book_vocab:
                cp = _ChapterProgress(chapters_to_generate)
            else:
                pbar = _ProgressBar(total=total)

            def _vocab_chunk_cb(done: int, total_chunks: int) -> None:
                if done == 0:
                    pbar.total = total_chunks
                    pbar.n = 0
                else:
                    pbar.n = done
                pbar.refresh()

            vocab_time = 0.0
            for chapter in chapters_to_generate:
                if is_book_vocab:
                    cp.start_chapter(chapter.index)
                ch_start = time.monotonic()
                progress = cp if is_book_vocab else pbar  # type: ignore[assignment]
                cards, usage = generate_vocab_for_chapter(
                    provider, chapter, book_title,
                    level=args.level, native_language=native_lang,
                    progress_bar=progress,
                    is_article=is_single,
                    topic=args.topic or "",
                    on_chunk_done=_vocab_chunk_cb if is_single else None,
                    parallel_chunks=args.parallel,
                )
                ch_elapsed = time.monotonic() - ch_start
                vocab_time += ch_elapsed
                all_cards.extend(cards)
                total_usage += usage
                if is_book_vocab:
                    ch_cost = format_cost(estimate_cost(usage, model))
                    cp.complete_chapter(chapter.index, len(cards), ch_elapsed, ch_cost)
                elif not is_single:
                    pbar.update(1)

            if is_book_vocab:
                cp.close()
                _print_summary(len(all_cards), vocab_time, total_usage, model)
            else:
                pbar.close()

        if not all_cards:
            cost = estimate_cost(total_usage, model)
            print(f"Error: No vocabulary cards were generated. Cost: {format_cost(cost)}",
                  file=sys.stderr)
            sys.exit(1)

        # Merge duplicates across chapters (same word may appear in multiple chapters)
        before = len(all_cards)
        all_cards = deduplicate_vocab(all_cards)
        if len(all_cards) < before:
            print(f"Merged {before - len(all_cards)} duplicate words"
                  f" ({before} → {len(all_cards)})")

        # Skip words already in Anki
        if existing_words:
            before = len(all_cards)
            all_cards = [
                c for c in all_cards
                if _vocab_base(vocab_word(c.question)) not in existing_words
            ]
            skipped = before - len(all_cards)
            if skipped:
                print(f"Skipped {skipped} words already in Anki"
                      f" ({before} → {len(all_cards)})")

        source_name = _lang_name(source_lang)
        deck_parts = [f"{source_name} {args.level}", book_title]
        if args.topic:
            deck_parts.append(_short_topic(args.topic))
        vocab_deck_title = " — ".join(deck_parts)
        file_parts = list(deck_parts)
        if args.chapters:
            file_parts.append(f"ch.{args.chapters}")
        file_name = " — ".join(file_parts)
        base_name = re.sub(r'[<>:"/\\|?*]', "", file_name).replace(' ', '_')
        output_path = args.output or f"{base_name}.apkg"
        if not output_path.endswith(".apkg"):
            output_path = str(Path(output_path) / f"{base_name}.apkg")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        package_vocab_flat(all_cards, vocab_deck_title, output_path)

        cost = estimate_cost(total_usage, model)
        print(f"\nDone! Generated {len(all_cards)} vocabulary cards. Cost: {format_cost(cost)}")
        print(f"Output: {output_path}\n")
        return

    if is_url or is_yt:
        source_url = args.file if is_url else f"https://www.youtube.com/watch?v={args.file}"
        all_cards, total_usage, all_media = _process_sequential(
            provider, chapters_to_generate, book_title, args.depth, lang,
            total=1, all_cards=[], chapters_dir="", is_article=True,
            source_url=source_url, is_programming=is_prog,
            topic=args.topic or "", parallel_chunks=args.parallel,
        )
        if not all_cards:
            cost = estimate_cost(total_usage, model)
            print(f"Error: No cards were generated. Cost: {format_cost(cost)}",
                  file=sys.stderr)
            sys.exit(1)

        base = _write_single_output(
            all_cards, deck_title, args.output,
            is_youtube=is_yt, media_files=all_media,
            depth=args.depth,
        )

        # Clean up temporary media files (already embedded in .apkg)
        _cleanup_media(all_media)

        cost = estimate_cost(total_usage, model)
        print(f"\nDone! Generated {len(all_cards)} cards. Cost: {format_cost(cost)}")
        print(f"Output: {base}.apkg\n")
    else:
        depth_label = f"d{args.depth}" if args.depth != 1 else ""
        base_name = re.sub(r'[<>:"/\\|?*]', "", book_title).replace(' ', '_')
        if depth_label:
            base_name = f"{base_name}_{depth_label}"
        output_dir = args.output or base_name
        # Single flat deck: summary, topic, or explicit --flat
        single_deck = args.depth == 0 or bool(args.topic) or args.flat
        chapters_dir = "" if single_deck else str(Path(output_dir) / "chapters")

        existing: dict[int, list[Card]] = {}
        if chapters_dir:
            existing = load_existing_chapters(chapters_dir)
            for idx, cards in sorted(existing.items()):
                if any(ch.index == idx for ch in chapters_to_generate):
                    all_cards.extend(cards)

            if existing:
                existing_in_scope = {idx for idx in existing if any(ch.index == idx for ch in chapters_to_generate)}
                if existing_in_scope:
                    print(f"Resuming: {len(existing_in_scope)}/{len(chapters_to_generate)} chapters already done"
                          f" ({len(all_cards)} cards)")

        pending = [ch for ch in chapters_to_generate if ch.index not in existing]
        total = len(chapters_to_generate)

        existing_counts: dict[int, int] | None = None
        if existing:
            existing_counts = {idx: len(cards) for idx, cards in existing.items()}

        if pending:
            if args.parallel:
                all_cards, total_usage, all_media = _process_parallel(
                    provider, pending, book_title, args.depth, lang, total, all_cards, chapters_dir,
                    is_programming=is_prog, topic=args.topic or "",
                    all_chapters=chapters_to_generate, existing_counts=existing_counts,
                )
            else:
                all_cards, total_usage, all_media = _process_sequential(
                    provider, pending, book_title, args.depth, lang, total, all_cards, chapters_dir,
                    is_programming=is_prog, topic=args.topic or "",
                    parallel_chunks=args.parallel,
                    all_chapters=chapters_to_generate, existing_counts=existing_counts,
                )

        if not all_cards:
            cost = estimate_cost(total_usage, model)
            print(f"Error: No cards were generated. Cost: {format_cost(cost)}",
                  file=sys.stderr)
            sys.exit(1)

        # Cross-chapter dedup for summary/topic mode
        if single_deck and len(all_cards) > 3:
            before = len(all_cards)
            all_cards = deduplicate(all_cards)
            if len(all_cards) < before:
                print(f"Removed {before - len(all_cards)} similar cards"
                      f" ({before} → {len(all_cards)})")
            # LLM consolidation — pick best among near-duplicates
            if args.depth == 0 or args.topic:
                print("Consolidating cards...")
                all_cards, cons_usage = consolidate_cards(
                    provider, all_cards, lang,
                )
                total_usage += cons_usage
                print(f"Final: {len(all_cards)} cards")

        _write_output(
            all_cards, deck_title, output_dir,
            full_book=(args.chapters is None),
            flat=single_deck,
            media_files=all_media,
        )

        # Clean up temporary media files (already embedded in .apkg)
        _cleanup_media(all_media)

        cost = estimate_cost(total_usage, model)
        cost_str = f" Cost: {format_cost(cost)}" if cost > 0 else ""
        n_ch = len(chapters_to_generate)
        print(f"\nDone! Generated {len(all_cards)} cards across {n_ch} chapter(s).{cost_str}")
        if single_deck:
            print(f"Output: {output_dir}.apkg\n")
        else:
            print(f"Output: {output_dir}/\n")


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

_TBL_HEADER = f"{'Chapter':<45} {'Cards':>5}  {'Time':>7}  {'Cost':>8}"
_TBL_SEP = "-" * 45 + " " + "-" * 5 + "  " + "-" * 7 + "  " + "-" * 8


def _tbl_row(title: str, cards: str, time_s: str, cost: str) -> str:
    short = title[:43] + "…" if len(title) > 44 else title
    return f"{short:<45} {cards:>5}  {time_s:>7}  {cost:>8}"


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
        self._cost: list[str] = [""] * self._n
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
                _fmt_elapsed(self._elapsed[i]), self._cost[i],
            )
        if st == "cached":
            return _tbl_row(title, str(self._cards[i]), "—", "—")
        if st == "active":
            s = _SPINNER[self._spin]
            elapsed = time.monotonic() - self._ch_start[i]
            return _tbl_row(title, s, _fmt_elapsed(elapsed), "")
        # pending
        return _tbl_row(title, "", "", "")

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
        self, chapter_index: int, cards: int, elapsed: float, cost: str,
    ) -> None:
        with self._lock:
            pos = self._pos.get(chapter_index)
            if pos is not None:
                self._state[pos] = "done"
                self._cards[pos] = cards
                self._elapsed[pos] = elapsed
                self._cost[pos] = cost
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
    total_cards: int, total_time: float, total_usage: TokenUsage, model: str,
    cached_cards: int = 0,
) -> None:
    cost = estimate_cost(total_usage, model)
    cost_str = format_cost(cost)
    cards_str = str(total_cards + cached_cards)
    if cached_cards:
        cards_str = f"{cards_str}"
    print(
        _TBL_SEP + "\n" +
        _tbl_row("Total", cards_str, _fmt_elapsed(total_time), cost_str),
        file=sys.stderr,
    )


def _process_sequential(
    provider: LLMProvider, chapters: list[Chapter], book_title: str, depth: int,
    lang: str, total: int, all_cards: list[Card], chapters_dir: str,
    is_article: bool = False, source_url: str = "", is_programming: bool = False,
    topic: str = "", parallel_chunks: bool = False,
    all_chapters: list[Chapter] | None = None, existing_counts: dict[int, int] | None = None,
) -> tuple[list[Card], TokenUsage, list[str]]:
    session_cards = 0
    total_usage = TokenUsage(0, 0)
    total_time = 0.0
    model = provider.model_name()
    all_media: list[str] = []

    is_book = not is_article

    if is_book:
        cp = _ChapterProgress(all_chapters or chapters, existing=existing_counts)
    else:
        pbar = _ProgressBar(total=total)

    def _chunk_cb(done: int, total_chunks: int) -> None:
        """Update progress bar based on chunk progress (for single-chapter sources)."""
        if done == 0:
            pbar.total = total_chunks
            pbar.n = 0
        else:
            pbar.n = done
        pbar.refresh()

    for chapter in chapters:
        if is_book:
            cp.start_chapter(chapter.index)

        ch_start = time.monotonic()
        chunk_cb = _chunk_cb if is_article else None
        progress = cp if is_book else pbar  # type: ignore[assignment]
        cards, usage = generate_cards_for_chapter(
            provider=provider,
            chapter=chapter,
            book_title=book_title,
            depth=depth,
            language=lang,
            progress_bar=progress,
            is_article=is_article,
            source_url=source_url,
            is_programming=is_programming,
            topic=topic,
            on_chunk_done=chunk_cb,
            parallel_chunks=parallel_chunks,
        )

        ch_media: list[str] = []
        media_dir = os.path.join(chapters_dir or ".", "media")
        if cards and chapter.images:
            book_media = process_book_images(
                cards, chapter.images, media_dir,
            )
            ch_media.extend(book_media)
            all_media.extend(book_media)

        ch_elapsed = time.monotonic() - ch_start
        total_time += ch_elapsed
        all_cards.extend(cards)
        session_cards += len(cards)
        total_usage += usage

        if cards and chapters_dir:
            package_single_chapter(
                cards, book_title, chapter.index, chapters_dir,
                media_files=ch_media,
            )

        if is_book:
            ch_cost = format_cost(estimate_cost(usage, model))
            cp.complete_chapter(chapter.index, len(cards), ch_elapsed, ch_cost)
        else:
            pbar.update(1)
            pbar.set_postfix_str(f"{session_cards} cards")

    if is_book:
        cp.close()
        cached = sum(existing_counts.values()) if existing_counts else 0
        _print_summary(session_cards, total_time, total_usage, model, cached_cards=cached)
    else:
        pbar.close()
    return all_cards, total_usage, all_media


class _QuietBar:
    """No-op progress bar to suppress per-chunk status in parallel mode."""

    def set_postfix_str(self, msg: str, refresh: bool = False) -> None:
        pass


def _process_vocab_parallel(
    provider: LLMProvider, chapters: list[Chapter], book_title: str,
    level: str, native_language: str, total: int,
    is_article: bool = False, topic: str = "",
) -> tuple[list[Card], TokenUsage]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total_usage = TokenUsage(0, 0)
    model = provider.model_name()
    session_words = 0
    chapter_start: dict[int, float] = {}
    quiet = _QuietBar()
    cards_by_chapter: dict[int, list[Card]] = {}

    wall_start = time.monotonic()
    cp = _ChapterProgress(chapters)

    def _run_vocab(ch: Chapter) -> tuple[list[Card], TokenUsage]:
        cp.start_chapter(ch.index)
        chapter_start[ch.index] = time.monotonic()
        return generate_vocab_for_chapter(
            provider=provider,
            chapter=ch,
            book_title=book_title,
            level=level,
            native_language=native_language,
            progress_bar=quiet,
            is_article=is_article,
            topic=topic,
            parallel_chunks=True,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_chapter = {
            executor.submit(_run_vocab, chapter): chapter
            for chapter in chapters
        }

        for future in as_completed(future_to_chapter):
            chapter = future_to_chapter[future]
            ch_elapsed = time.monotonic() - chapter_start[chapter.index]
            try:
                cards, usage = future.result()
                cards_by_chapter[chapter.index] = cards
                session_words += len(cards)
                total_usage += usage

                ch_cost = format_cost(estimate_cost(usage, model))
                cp.complete_chapter(chapter.index, len(cards), ch_elapsed, ch_cost)
            except Exception as e:
                cp.complete_chapter(chapter.index, 0, ch_elapsed, "error")
                print(f"Warning: Failed to process \"{chapter.title}\": {e}",
                      file=sys.stderr)

    cp.close()
    all_cards: list[Card] = []
    for idx in sorted(cards_by_chapter):
        all_cards.extend(cards_by_chapter[idx])
    wall_elapsed = time.monotonic() - wall_start
    _print_summary(session_words, wall_elapsed, total_usage, model)
    return all_cards, total_usage


def _process_parallel(
    provider: LLMProvider, chapters: list[Chapter], book_title: str, depth: int,
    lang: str, total: int, all_cards: list[Card], chapters_dir: str,
    is_programming: bool = False, topic: str = "",
    all_chapters: list[Chapter] | None = None, existing_counts: dict[int, int] | None = None,
) -> tuple[list[Card], TokenUsage, list[str]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    session_cards = 0
    total_usage = TokenUsage(0, 0)
    model = provider.model_name()
    chapter_start: dict[int, float] = {}
    all_media: list[str] = []
    cards_by_chapter: dict[int, list[Card]] = {}

    quiet = _QuietBar()
    wall_start = time.monotonic()
    cp = _ChapterProgress(all_chapters or chapters, existing=existing_counts)

    def _run_chapter(ch: Chapter) -> tuple[list[Card], TokenUsage]:
        cp.start_chapter(ch.index)
        chapter_start[ch.index] = time.monotonic()
        return generate_cards_for_chapter(
            provider=provider,
            chapter=ch,
            book_title=book_title,
            depth=depth,
            language=lang,
            progress_bar=quiet,
            is_programming=is_programming,
            topic=topic,
            parallel_chunks=True,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_chapter = {
            executor.submit(_run_chapter, chapter): chapter
            for chapter in chapters
        }

        for future in as_completed(future_to_chapter):
            chapter = future_to_chapter[future]
            ch_elapsed = time.monotonic() - chapter_start[chapter.index]
            try:
                cards, usage = future.result()

                ch_media: list[str] = []
                media_dir = os.path.join(chapters_dir or ".", "media")
                if cards and chapter.images:
                    book_media = process_book_images(
                        cards, chapter.images, media_dir,
                    )
                    ch_media.extend(book_media)
                    all_media.extend(book_media)

                cards_by_chapter[chapter.index] = cards
                session_cards += len(cards)
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens

                if cards and chapters_dir:
                    package_single_chapter(
                        cards, book_title, chapter.index, chapters_dir,
                        media_files=ch_media,
                    )

                ch_cost = format_cost(estimate_cost(usage, model))
                cp.complete_chapter(chapter.index, len(cards), ch_elapsed, ch_cost)
            except Exception as e:
                cp.complete_chapter(chapter.index, 0, ch_elapsed, "error")
                print(f"Warning: Failed to process \"{chapter.title}\": {e}",
                      file=sys.stderr)

    cp.close()
    for idx in sorted(cards_by_chapter):
        all_cards.extend(cards_by_chapter[idx])
    wall_elapsed = time.monotonic() - wall_start
    cached = sum(existing_counts.values()) if existing_counts else 0
    _print_summary(session_cards, wall_elapsed, total_usage, model, cached_cards=cached)
    return all_cards, total_usage, all_media


if __name__ == "__main__":
    main()
