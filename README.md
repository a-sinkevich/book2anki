# book2anki

AI-powered tool to convert books (EPUB/PDF), web articles, and YouTube videos into Anki flashcards for spaced repetition learning. Also supports vocabulary extraction for language learners. Uses Claude to generate high-quality cards from any content.

## Quick start

1. Download the binary for your platform from [Releases](https://github.com/a-sinkevich/book2anki/releases/latest):
   - **macOS (Apple Silicon)**: `book2anki-macos-arm64`
   - **Linux**: `book2anki-linux-amd64`
   - **Windows**: `book2anki-windows-amd64.exe`
2. Set up an LLM provider (choose one):
   - **Claude CLI** (recommended if you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed): no extra setup needed — book2anki auto-detects and uses it with Opus
   - **Anthropic API**: get a key from [Anthropic](https://console.anthropic.com/settings/keys), [add credit](https://console.anthropic.com/settings/billing) (prepaid, see [costs](#costs)), and save it in `~/.book2anki.env` (Windows: `C:\Users\<YourName>\.book2anki.env`):
     ```
     ANTHROPIC_API_KEY=your-key
     ```
3. Open a terminal (macOS: Terminal.app, Windows: PowerShell, Linux: any terminal) and make the binary executable (once, macOS/Linux only):
   ```bash
   chmod +x book2anki-macos-arm64    # or book2anki-linux-amd64
   ```
   > **macOS**: if you get "cannot be opened because the developer cannot be verified", run:
   > `xattr -d com.apple.quarantine book2anki-macos-arm64`

4. Run (examples for macOS, replace binary name for your platform):
   ```bash
   ./book2anki-macos-arm64 mybook.epub
   ./book2anki-macos-arm64 mybook.pdf --depth 2   # more detailed cards
   ./book2anki-macos-arm64 "https://en.wikipedia.org/wiki/Spaced_repetition"
   ./book2anki-macos-arm64 "https://www.youtube.com/watch?v=lrSB9gEUJEQ"
   ./book2anki-macos-arm64 MnT1xgZgkpk --depth 3  # YouTube video ID, comprehensive
   ```

## Install from source

Requires **Python 3.10+**.

```bash
git clone https://github.com/a-sinkevich/book2anki.git
cd book2anki
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Then run with:
```bash
python -m book2anki mybook.epub
```

## Usage

In the examples below, replace `book2anki` with how you run it:
- **Binary**: `./book2anki-macos-arm64` (or the filename for your platform)
- **From source**: `python -m book2anki`

```bash
# Basic — generates Anki deck with core-level cards
book2anki mybook.epub

# Choose depth: 0=summary (2-3 cards/chapter), 1=core, 2=detailed, 3=comprehensive
book2anki mybook.epub --depth 0   # just the key takeaways
book2anki mybook.pdf --depth 2

# Specific chapters
book2anki mybook.epub --chapters 3
book2anki mybook.epub --chapters 1,3,5
book2anki mybook.epub --chapters 3-7
book2anki mybook.epub --chapters 1,3-5,8

# From a URL — use quotes to prevent shell interpretation
book2anki "https://example.com/article"
book2anki "https://www.youtube.com/watch?v=VIDEO_ID"
book2anki VIDEO_ID    # just the YouTube video ID (no quotes needed)

# Generate cards in a different language than the source
book2anki mybook.epub --lang ru    # English book → Russian cards

# Focus on a specific topic
book2anki mybook.epub --topic "dopamine"   # only cards about dopamine

# Vocabulary mode — extract words above your level for language learning
book2anki mybook.epub --vocab --level B2 --lang ru    # English book, B2 learner, translate to Russian
book2anki "https://example.com/article" --vocab --level C1 --lang ru
book2anki mybook.epub --vocab --level B2 --lang ru --chapters 1-3   # specific chapters
book2anki mybook.epub --vocab --level C1 --lang ru --topic "medicine"  # only medical vocabulary

# Parallel processing — faster for multi-chapter books
book2anki mybook.epub --parallel
book2anki mybook.epub --vocab --level B2 --lang ru --parallel

# Model selection
book2anki mybook.epub --model sonnet   # Sonnet (faster, cheaper via API)
book2anki mybook.epub --model opus     # Opus via API (~15x cost)
book2anki mybook.epub --model cli      # Force claude CLI

# Combine flags
book2anki mybook.epub --depth 0 --topic "agriculture"  # 2-3 cards about agriculture
book2anki mybook.epub --depth 2 --topic "memory" --lang ru

```

## Topic mode ideas

The `--topic` flag filters cards to a specific subject — works with books, articles, and YouTube:

```bash
# Extract a "hidden" topic from a book that isn't specifically about it
book2anki thinking_fast_and_slow.epub --topic "anchoring"

# Same topic across multiple books for different perspectives
book2anki sapiens.epub --topic "agriculture"
book2anki guns_germs_steel.epub --topic "agriculture"

# Grab one angle from a broad Wikipedia article
book2anki "https://en.wikipedia.org/wiki/Roman_Empire" --topic "military organization"

# Extract just what you need from a long YouTube lecture
book2anki "https://youtube.com/watch?v=VIDEO_ID" --topic "compound interest"

# Quick summary on a topic: depth 0 + topic = 2-3 cards about X
book2anki neuroscience.epub --depth 0 --topic "synaptic plasticity"
```

## Output

```
Book-Title/
  Book-Title.apkg          # combined Anki deck
  chapters/
    01 - chapter-name.apkg  # per-chapter decks
    media/                  # book images (when EPUB contains figures)
```

With `--depth 0` or `--topic`, output is a single flat deck (no chapter subdecks).

Vocabulary mode outputs a flat deck named `{Language} {Level} — {Book Title}` (e.g. `English B2 — The Great Gatsby`). Running for different chapter ranges produces files that merge into the same Anki deck on import.

## How it works

1. **Parse** — EPUB chapters via TOC, PDF via heading detection, web via article extraction + `srcset` for high-res images, YouTube via transcript API
2. **Chunk** — split chapters into overlapping segments fitting the model's context window (~80% of limit minus output reserve)
3. **Generate** — each chunk → Claude (Opus via CLI or Sonnet via API) with depth/language/content-type-aware prompt; image captions included so the model can reference figures
4. **Dedup** — `SequenceMatcher`-based similarity dedup within chunks; LLM consolidation pass across chapters in summary/topic modes
5. **Package** — `.apkg` via [genanki](https://github.com/kerrickstaley/genanki); per-chapter subdecks for books, flat deck for articles/summary/topic

Chapters are saved individually on completion — interrupt and resume without re-generating.

## Development

```bash
# Install dev dependencies (with venv activated)
pip install -e ".[dev]" build

# Run checks individually
python -m flake8 book2anki/ tests/    # lint
python -m mypy book2anki/             # type check
python -m pytest tests/ -v            # tests

# Or use make (Linux/macOS)
make check       # lint + typecheck + tests
make build       # check + build wheel/sdist
make clean       # remove build artifacts
make install-dev # install dev deps
```

## Costs

If you use the **Claude CLI** (default when available), there is no direct API cost — usage goes through your Claude Code subscription.

When using the **Anthropic API**, typical costs:

| Source | Depth 0 (summary) | Depth 1 (core) | Depth 2 (detailed) | Depth 3 (comprehensive) |
|--------|:-:|:-:|:-:|:-:|
| YouTube video (1 hour) | ~$0.05 | ~$0.06 | ~$0.07 | ~$0.13 |
| Book (full) | $0.20–$1.00 | $0.50–$2.00 | $1.00–$3.00 | $2.00–$5.00 |

Vocabulary mode (`--vocab`) costs roughly the same as depth 2–3 per chapter. Using `--model opus` via API is ~15x more expensive than Sonnet. Tip: use `--chapters` to process specific chapters instead of the whole book.

## Features

- **EPUB, PDF, URL & YouTube** — books, web articles, or video transcripts
- **Four depth levels**: summary (2-3 cards/chapter), core ideas, detailed, or comprehensive
- **Vocabulary mode** (`--vocab --level B2 --lang ru`) — extract words/phrases above your CEFR level with IPA pronunciation, etymology, example sentences, and translation
- **Anki-aware dedup** — reads your existing Anki collection to skip words you already have
- **Topic filter** (`--topic`) — generate cards only about a specific subject (works with both regular and vocab modes)
- **Images** — extracts figures from EPUB books and web articles, includes them in relevant cards
- **Smart dedup** — similarity-based dedup within chunks; LLM consolidation across chapters in summary/topic modes; vocab duplicates merged with multiple contexts
- **Dark & light theme** — cards adapt to your Anki theme
- **Parallel processing** (`--parallel`) — process multiple chapters simultaneously
- **Claude CLI support** — auto-detects `claude` CLI for zero-cost generation, falls back to API
- **Model selection** (`--model`) — choose between Sonnet (fast/cheap), Opus (highest quality), or CLI
- **Resume on interrupt**: re-run the same command and it skips already-generated chapters
- **Auto language detection** with `--lang` override
- **Progress bar** with per-chapter cost breakdown during generation
