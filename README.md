# book2anki

Convert nonfiction books (EPUB/PDF), articles (URL), and YouTube videos into Anki flashcard decks using LLMs.

## Quick start

1. Download the binary for your platform from [Releases](https://github.com/a-sinkevich/book2anki/releases/latest):
   - **macOS (Apple Silicon)**: `book2anki-macos-arm64`
   - **Linux**: `book2anki-linux-amd64`
   - **Windows**: `book2anki-windows-amd64.exe`
2. Get an API key from [Anthropic](https://console.anthropic.com/settings/keys) and [add credit](https://console.anthropic.com/settings/billing) (the API is prepaid, see [costs](#costs) below). If you already have `ANTHROPIC_API_KEY` set in your environment, skip to step 4.
3. Create `~/.book2anki.env` (on Windows: `C:\Users\<YourName>\.book2anki.env`):
   ```
   ANTHROPIC_API_KEY=your-key
   GOOGLE_API_KEY=your-key   # optional, for --diagrams
   ```
4. Open a terminal (macOS: Terminal.app, Windows: PowerShell, Linux: any terminal) and make the binary executable (once, macOS/Linux only):
   ```bash
   chmod +x book2anki-macos-arm64    # or book2anki-linux-amd64
   ```
   > **macOS**: if you get "cannot be opened because the developer cannot be verified", run:
   > `xattr -d com.apple.quarantine book2anki-macos-arm64`

5. Run (examples for macOS, replace binary name for your platform):
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

# Choose depth: 1=core, 2=detailed, 3=comprehensive
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

# Generate visual diagrams for concepts (requires GOOGLE_API_KEY)
book2anki mybook.epub --diagrams
```

## Diagrams

The `--diagrams` flag generates educational images for cards where visual representation aids understanding (e.g. brain anatomy, system architecture, data flow). Images are generated using the Gemini API.

**Setup:**
1. Get an API key from [Google AI Studio](https://aistudio.google.com/apikey)
2. Add it to `~/.book2anki.env`:
   ```
   GOOGLE_API_KEY=your-key
   ```
3. Install the diagrams dependency (from source only — binaries include it):
   ```bash
   pip install -e ".[diagrams]"
   ```

The tool automatically adapts diagram style to the content: realistic anatomical illustrations for biology, architecture diagrams for programming, maps for geography, etc.

## Output

```
Book-Title/
  Book-Title.apkg          # combined Anki deck
  chapters/
    01 - chapter-name.apkg  # per-chapter decks
    media/                  # diagram images (when --diagrams is used)
```

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

The tool uses the Anthropic API (card generation) and optionally the Gemini API (diagrams). Typical costs:

| Source | Depth 1 (core) | Depth 2 (detailed) | Depth 3 (comprehensive) |
|--------|:-:|:-:|:-:|
| YouTube video (1 hour) | ~$0.06 | ~$0.07 | ~$0.13 |
| Book (full) | $0.50–$2.00 | $1.00–$3.00 | $2.00–$5.00 |

Diagrams add ~$0.04–$0.07 per image depending on the Gemini model used. A typical book chapter generates 2–5 diagrams.

## Features

- **EPUB, PDF, URL & YouTube** — books, web articles, or video transcripts
- **Three depth levels**: core ideas, detailed coverage, or comprehensive
- **Visual diagrams** — AI-generated images for concepts that benefit from visual representation
- **Resume on interrupt**: re-run the same command and it skips already-generated chapters
- **Auto language detection** (English, Russian)
- **Progress bar** with per-chapter cost breakdown during generation
