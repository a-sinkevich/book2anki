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
from book2anki.generator import LLMProvider, generate_cards_for_chapter, estimate_cost, format_cost
from book2anki.prompts import detect_programming
from book2anki.diagram_gen import (
    DiagramResult, is_gemini_available, process_book_images, process_diagrams,
)
from book2anki.packager import (
    package_cards, package_cards_flat, package_single_chapter,
    load_existing_chapters, YOUTUBE_MODEL,
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


def _create_provider() -> LLMProvider:
    from book2anki.provider_claude import ClaudeProvider
    return ClaudeProvider()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="book2anki",
        description="Convert nonfiction books (EPUB/PDF) into Anki flashcard decks using LLMs.",
    )
    parser.add_argument("file", help="Path to .epub or .pdf file, or a URL (article/YouTube)")
    parser.add_argument(
        "--depth", type=int, choices=[1, 2, 3], default=1,
        help="Card generation depth: 1=core, 2=detailed, 3=comprehensive (default: 1)",
    )
    parser.add_argument(
        "--lang", default=None,
        help="Card language (default: auto-detect). "
             "Use to generate cards in a different language, e.g. --lang ru",
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
        "--diagrams", action="store_true",
        help="Generate inline SVG diagrams for visual concepts (opt-in)",
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


def _write_single_output(
    all_cards: list[Card], book_title: str, output: str | None,
    is_youtube: bool = False, media_files: list[str] | None = None,
) -> str:
    """Write a single .apkg file for a URL source. Returns output path."""
    base_name = output or re.sub(r'[<>:"/\\|?*]', "", book_title).replace(" ", "_")
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
    media_files: list[str] | None = None,
) -> None:
    """Write final Anki deck output files."""
    if full_book:
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

    print(f'"{book_title}" — {len(chapters)} chapter(s) extracted.')
    print(f"Parameters: depth={args.depth}"
          f"{', chapters=' + args.chapters if args.chapters else ', chapters=all'}"
          f"{', lang=' + args.lang if args.lang else ', lang=auto'}"
          f"{', diagrams' if args.diagrams else ''}"
          f"{', parallel' if args.parallel else ''}")

    chapters_to_generate = _select_chapters(chapters, args.chapters)

    all_text = "\n".join(ch.text for ch in chapters_to_generate)
    lang = detect_language(all_text, override=args.lang)
    is_prog = detect_programming(all_text)
    diagram_mode = "svg"
    if args.diagrams and is_gemini_available():
        diagram_mode = "gemini"
    total_book_images = sum(len(ch.images) for ch in chapters_to_generate)
    print(f"Language: {lang}")
    if is_prog:
        print("Content: programming (code-aware cards)")
    if total_book_images:
        print(f"Book images: {total_book_images} figures extracted")
    print()

    try:
        provider = _create_provider()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Cards model: {provider.model_name()}")
    if args.diagrams:
        if diagram_mode == "gemini":
            print("Diagrams: Gemini image generation")
        else:
            print("Diagrams: inline SVG (set GOOGLE_API_KEY for Gemini images)")
    print()

    all_cards: list[Card] = []
    diag_result = DiagramResult()

    total_usage = TokenUsage(0, 0)
    model = provider.model_name()

    if is_url or is_yt:
        source_url = args.file if is_url else f"https://www.youtube.com/watch?v={args.file}"
        all_cards, total_usage, diag_result = _process_sequential(
            provider, chapters_to_generate, book_title, args.depth, lang,
            total=1, all_cards=[], chapters_dir="", is_article=True,
            source_url=source_url, is_programming=is_prog,
            diagrams=args.diagrams, diagram_mode=diagram_mode,
        )
        if not all_cards:
            print("Error: No cards were generated.", file=sys.stderr)
            sys.exit(1)

        base = _write_single_output(
            all_cards, book_title, args.output,
            is_youtube=is_yt, media_files=diag_result.media_files,
        )
        text_cost = estimate_cost(total_usage, model)
        total_cost = text_cost + diag_result.cost
        diag_str = _format_diagram_summary(diag_result)
        print(f"\nDone! Generated {len(all_cards)} cards. Cost: {format_cost(total_cost)}{diag_str}")
        print(f"Output: {base}.apkg\n")
    else:
        base_name = re.sub(r'[<>:"/\\|?*]', "", book_title).replace(' ', '_')
        output_dir = args.output or base_name
        chapters_dir = str(Path(output_dir) / "chapters")

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

        if pending:
            if args.parallel:
                all_cards, total_usage, diag_result = _process_parallel(
                    provider, pending, book_title, args.depth, lang, total, all_cards, chapters_dir,
                    is_programming=is_prog, diagrams=args.diagrams,
                    diagram_mode=diagram_mode,
                )
            else:
                all_cards, total_usage, diag_result = _process_sequential(
                    provider, pending, book_title, args.depth, lang, total, all_cards, chapters_dir,
                    is_programming=is_prog, diagrams=args.diagrams,
                    diagram_mode=diagram_mode,
                )

        if not all_cards:
            print("Error: No cards were generated.", file=sys.stderr)
            sys.exit(1)

        _write_output(
            all_cards, book_title, output_dir,
            full_book=(args.chapters is None),
            media_files=diag_result.media_files,
        )

        text_cost = estimate_cost(total_usage, model)
        total_cost = text_cost + diag_result.cost
        cost_str = f" Cost: {format_cost(total_cost)}" if total_cost > 0 else ""
        diag_str = _format_diagram_summary(diag_result)
        n_ch = len(chapters_to_generate)
        print(f"\nDone! Generated {len(all_cards)} cards across {n_ch} chapter(s).{cost_str}{diag_str}")
        print(f"Output: {output_dir}/\n")


def _format_diagram_summary(diag: DiagramResult) -> str:
    """Format diagram generation summary for output."""
    if not diag.generated and not diag.cached:
        return ""
    parts = []
    total = diag.generated + diag.cached
    parts.append(f"\nDiagrams: {total} generated")
    if diag.cached:
        parts.append(f" ({diag.cached} cached)")
    if diag.failed:
        parts.append(f", {diag.failed} failed")
    if diag.primary_model:
        parts.append(f", model: {diag.primary_model}")
    if diag.generated:
        parts.append(f", cost: {diag.cost_str}")
    return "".join(parts)


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    return f"{m}m{sec:02d}s"


def _fmt_mm_ss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


_TBL_HEADER = (
    f"{'Chapter':<45} {'Cards':>5}  {'Diag':>4}  {'Time':>7}"
    f"  {'Cost':>8}  {'DiagCost':>8}  {'Total':>8}"
)
_TBL_SEP = (
    "-" * 45 + " " + "-" * 5 + "  " + "-" * 4 + "  " + "-" * 7
    + "  " + "-" * 8 + "  " + "-" * 8 + "  " + "-" * 8
)


def _tbl_row(
    title: str, cards: int, elapsed: float, cost: str,
    diags: int = 0, diag_cost: str = "", total_cost: str = "",
) -> str:
    short = title[:43] + "…" if len(title) > 44 else title
    diag_s = str(diags) if diags else ""
    return (
        f"{short:<45} {cards:>5}  {diag_s:>4}  {_fmt_elapsed(elapsed):>7}"
        f"  {cost:>8}  {diag_cost:>8}  {total_cost:>8}"
    )


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


def _process_sequential(
    provider: LLMProvider, chapters: list[Chapter], book_title: str, depth: int,
    lang: str, total: int, all_cards: list[Card], chapters_dir: str,
    is_article: bool = False, source_url: str = "", is_programming: bool = False,
    diagrams: bool = False, diagram_mode: str = "svg",
) -> tuple[list[Card], TokenUsage, DiagramResult]:
    session_cards = 0
    total_usage = TokenUsage(0, 0)
    total_time = 0.0
    model = provider.model_name()
    all_diagrams = DiagramResult()

    show_table = not is_article
    pbar = _ProgressBar(total=total, initial=total - len(chapters))
    if show_table:
        pbar.write(_TBL_HEADER)
        pbar.write(_TBL_SEP)
    for chapter in chapters:
        ch_start = time.monotonic()
        cards, usage = generate_cards_for_chapter(
            provider=provider,
            chapter=chapter,
            book_title=book_title,
            depth=depth,
            language=lang,
            progress_bar=pbar,
            is_article=is_article,
            source_url=source_url,
            is_programming=is_programming,
            diagrams=diagrams,
            diagram_mode=diagram_mode,
        )

        ch_diag = DiagramResult()
        ch_media: list[str] = []
        media_dir = os.path.join(chapters_dir or ".", "media")
        if cards and chapter.images:
            book_media = process_book_images(
                cards, chapter.images, media_dir,
            )
            ch_media.extend(book_media)
            all_diagrams.media_files.extend(book_media)

        if cards and diagrams and diagram_mode == "gemini":
            ch_diag = process_diagrams(
                cards, media_dir,
                status_fn=lambda m: pbar.set_postfix_str(m),
                language=lang, is_programming=is_programming,
            )
            ch_media.extend(ch_diag.media_files)
            all_diagrams.media_files.extend(ch_diag.media_files)
            all_diagrams.generated += ch_diag.generated
            all_diagrams.cached += ch_diag.cached
            all_diagrams.failed += ch_diag.failed
            for m, c in ch_diag.model_counts.items():
                all_diagrams.model_counts[m] = (
                    all_diagrams.model_counts.get(m, 0) + c
                )

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

        if show_table:
            ch_text_cost = estimate_cost(usage, model)
            ch_cost = format_cost(ch_text_cost)
            n_diag = ch_diag.generated + ch_diag.cached
            ch_dcost = ch_diag.cost_str if ch_diag.generated else ""
            ch_total = format_cost(ch_text_cost + ch_diag.cost)
            pbar.write(_tbl_row(
                chapter.title, len(cards), ch_elapsed, ch_cost,
                diags=n_diag, diag_cost=ch_dcost, total_cost=ch_total,
            ))
        pbar.update(1)
        pbar.set_postfix_str(f"{session_cards} cards")

    pbar.close()
    if show_table:
        text_cost = estimate_cost(total_usage, model)
        total_diags = all_diagrams.generated + all_diagrams.cached
        total_dcost = all_diagrams.cost_str if all_diagrams.generated else ""
        combined = format_cost(text_cost + all_diagrams.cost)
        print(_TBL_SEP, file=sys.stderr)
        print(_tbl_row(
            "Total", session_cards, total_time, format_cost(text_cost),
            diags=total_diags, diag_cost=total_dcost, total_cost=combined,
        ), file=sys.stderr)
    return all_cards, total_usage, all_diagrams


def _process_parallel(
    provider: LLMProvider, chapters: list[Chapter], book_title: str, depth: int,
    lang: str, total: int, all_cards: list[Card], chapters_dir: str,
    is_programming: bool = False, diagrams: bool = False,
    diagram_mode: str = "svg",
) -> tuple[list[Card], TokenUsage, DiagramResult]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    session_cards = 0
    total_usage = TokenUsage(0, 0)
    total_time = 0.0
    model = provider.model_name()
    chapter_start: dict[int, float] = {}
    all_diagrams = DiagramResult()

    pbar = _ProgressBar(total=total, initial=total - len(chapters))
    pbar.write(_TBL_HEADER)
    pbar.write(_TBL_SEP)
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_chapter = {}
        for chapter in chapters:
            chapter_start[chapter.index] = time.monotonic()
            future_to_chapter[executor.submit(
                generate_cards_for_chapter,
                provider=provider,
                chapter=chapter,
                book_title=book_title,
                depth=depth,
                language=lang,
                is_programming=is_programming,
                diagrams=diagrams,
                diagram_mode=diagram_mode,
            )] = chapter

        for future in as_completed(future_to_chapter):
            chapter = future_to_chapter[future]
            ch_elapsed = time.monotonic() - chapter_start[chapter.index]
            try:
                cards, usage = future.result()

                ch_diag = DiagramResult()
                ch_media: list[str] = []
                media_dir = os.path.join(chapters_dir, "media")
                if cards and chapter.images:
                    book_media = process_book_images(
                        cards, chapter.images, media_dir,
                    )
                    ch_media.extend(book_media)
                    all_diagrams.media_files.extend(book_media)

                if cards and diagrams and diagram_mode == "gemini":
                    ch_diag = process_diagrams(
                        cards, media_dir, language=lang,
                        is_programming=is_programming,
                    )
                    ch_media.extend(ch_diag.media_files)
                    all_diagrams.media_files.extend(ch_diag.media_files)
                    all_diagrams.generated += ch_diag.generated
                    all_diagrams.cached += ch_diag.cached
                    all_diagrams.failed += ch_diag.failed
                    for m, c in ch_diag.model_counts.items():
                        all_diagrams.model_counts[m] = (
                            all_diagrams.model_counts.get(m, 0) + c
                        )

                all_cards.extend(cards)
                session_cards += len(cards)
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                total_time += ch_elapsed

                if cards:
                    package_single_chapter(
                        cards, book_title, chapter.index, chapters_dir,
                        media_files=ch_media,
                    )

                ch_text_cost = estimate_cost(usage, model)
                ch_cost = format_cost(ch_text_cost)
                n_diag = ch_diag.generated + ch_diag.cached
                ch_dcost = ch_diag.cost_str if ch_diag.generated else ""
                ch_total = format_cost(ch_text_cost + ch_diag.cost)
                pbar.write(_tbl_row(
                    chapter.title, len(cards), ch_elapsed, ch_cost,
                    diags=n_diag, diag_cost=ch_dcost, total_cost=ch_total,
                ))
                pbar.update(1)
                pbar.set_postfix_str(f"{session_cards} cards")
            except Exception as e:
                pbar.write(f"Warning: Failed to process \"{chapter.title}\": {e}")
                pbar.update(1)

    pbar.close()
    text_cost = estimate_cost(total_usage, model)
    total_diags = all_diagrams.generated + all_diagrams.cached
    total_dcost = all_diagrams.cost_str if all_diagrams.generated else ""
    combined = format_cost(text_cost + all_diagrams.cost)
    print(_TBL_SEP, file=sys.stderr)
    print(_tbl_row(
        "Total", session_cards, total_time, format_cost(text_cost),
        diags=total_diags, diag_cost=total_dcost, total_cost=combined,
    ), file=sys.stderr)
    return all_cards, total_usage, all_diagrams


if __name__ == "__main__":
    main()
