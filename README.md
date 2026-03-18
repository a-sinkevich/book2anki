# book2anki

Convert nonfiction books (EPUB/PDF) and articles (URL) into Anki flashcard decks using LLMs.

## Prerequisites

**Python 3.10+** is required.

- **macOS**: `brew install python` (or download from [python.org](https://www.python.org/downloads/))
- **Windows**: Download from [python.org](https://www.python.org/downloads/) — check "Add to PATH" during install
- **Linux (Ubuntu/Debian)**: `sudo apt install python3 python3-venv python3-pip`
- **Linux (Fedora)**: `sudo dnf install python3 python3-pip`

Verify: `python --version` (should show 3.10 or higher).

**API key**: Get one from [Anthropic](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/).

## Setup

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows (cmd)
.venv\Scripts\activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -e .
```

Set your API key by creating `~/.book2anki.env`:
```
ANTHROPIC_API_KEY=your-key
```

On Windows, this file goes in `C:\Users\<YourName>\.book2anki.env`.

You can also place a `.env` file in the current working directory (takes precedence), or set the variable as a traditional environment variable.

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

# Use GPT-4o instead of Claude
book2anki mybook.epub --model gpt-4o
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
python -m pytest tests/ -v            # tests (67 tests)

# Or use make (Linux/macOS)
make check       # lint + typecheck + tests
make build       # check + build wheel/sdist
make binary      # check + standalone .pyz binary (requires shiv)
make clean       # remove build artifacts
make install-dev # install all dev deps including shiv and build
```

## Features

- **EPUB, PDF & URL** — books or web articles
- **Three depth levels**: core ideas, detailed coverage, or comprehensive
- **Resume on interrupt**: re-run the same command and it skips already-generated chapters
- **Auto language detection** (English, Russian)
- **Progress bar** with live status during generation
