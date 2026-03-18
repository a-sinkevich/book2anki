# book2anki

Convert nonfiction books (EPUB/PDF) and articles (URL) into Anki flashcard decks using LLMs.

## Quick start

1. Download the binary for your platform from [Releases](https://github.com/a-sinkevich/book2anki/releases/latest):
   - **macOS (Apple Silicon)**: `book2anki-macos-arm64`
   - **Linux**: `book2anki-linux-amd64`
   - **Windows**: `book2anki-windows-amd64.exe`
2. Get an API key from [Anthropic](https://console.anthropic.com/settings/keys) and [add credit](https://console.anthropic.com/settings/billing) (the API is prepaid; a typical book costs $0.50–$2.00)
3. Create `~/.book2anki.env` (on Windows: `C:\Users\<YourName>\.book2anki.env`):
   ```
   ANTHROPIC_API_KEY=your-key
   ```
4. Open a terminal (macOS: Terminal.app, Windows: PowerShell, Linux: any terminal), navigate to the folder with the downloaded binary and your book, and run:
   ```bash
   # macOS
   chmod +x book2anki-macos-arm64
   ./book2anki-macos-arm64 mybook.epub

   # Linux
   chmod +x book2anki-linux-amd64
   ./book2anki-linux-amd64 mybook.epub

   # Windows (PowerShell)
   .\book2anki-windows-amd64.exe mybook.epub
   ```

   > **macOS note**: if you get "cannot be opened because the developer cannot be verified", run:
   > `xattr -d com.apple.quarantine book2anki-macos-arm64`

## Install from source

Requires **Python 3.10+**.

```bash
git clone https://github.com/a-sinkevich/book2anki.git
cd book2anki
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

## Usage

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

# From a URL (article → single flat deck)
book2anki https://example.com/article
```

## Output

```
Book-Title/
  Book-Title.apkg          # combined Anki deck
  chapters/
    01 - chapter-name.apkg  # per-chapter decks
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

## Features

- **EPUB, PDF & URL** — books or web articles
- **Three depth levels**: core ideas, detailed coverage, or comprehensive
- **Resume on interrupt**: re-run the same command and it skips already-generated chapters
- **Auto language detection** (English, Russian)
- **Progress bar** with live status during generation
