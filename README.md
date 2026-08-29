# book2anki

AI-powered tool to convert books (EPUB/PDF), web articles, and YouTube videos into Anki flashcards for spaced repetition learning. Also supports vocabulary extraction for language learners. Uses Claude to generate high-quality cards from any content.

## Quick start

1. Download the binary for your platform from [Releases](https://github.com/a-sinkevich/book2anki/releases/latest):
   - **macOS (Apple Silicon)**: `book2anki-macos-arm64`
   - **Linux**: `book2anki-linux-amd64`
   - **Windows**: `book2anki-windows-amd64.exe`
2. Set up an LLM provider (choose one):
   - **Claude CLI** (recommended if you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed): no extra setup needed — book2anki auto-detects and uses it with Opus
   - **Anthropic API**: get a key from [Anthropic](https://console.anthropic.com/settings/keys), [add credit](https://console.anthropic.com/settings/billing), and save it in `~/.book2anki.env` (Windows: `C:\Users\<YourName>\.book2anki.env`):
     ```
     ANTHROPIC_API_KEY=your-key
     ```
   - **OpenAI API**: get a key from [OpenAI](https://platform.openai.com/api-keys) and save it in `~/.book2anki.env`:
     ```
     OPENAI_API_KEY=your-key
     ```
     Then use `--model gpt5.5` or any GPT/o-series model.
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
   ./book2anki-macos-arm64 --prompt "Fundamentals of cognitive load theory for software engineering"
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

# Choose depth: 0=essential summary, 1=core, 2=detailed, 3=comprehensive
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

# From a study prompt — no source file needed
book2anki --prompt "Fundamentals of cognitive load theory: key principles and how to apply them in software engineering"
book2anki --prompt "Java memory model refresher for senior engineers" --depth 2

# Generate cards in a different language than the source
book2anki mybook.epub --lang ru    # English book → Russian cards

# Focus on a specific topic
book2anki mybook.epub --topic "dopamine"   # only cards about dopamine

# Vocabulary mode — extract words above your level for language learning
book2anki mybook.epub --vocab --level B2 --lang ru    # English book, B2 learner, translate to Russian
book2anki "https://example.com/article" --vocab --level C1 --lang ru
book2anki mybook.epub --vocab --level B2 --lang ru --chapters 1-3   # specific chapters
book2anki mybook.epub --vocab --level C1 --lang ru --topic "medicine"  # only medical vocabulary

# Vocab card direction (--vocab-mode): production (default) or recognition
book2anki mybook.epub --vocab --level C1 --lang ru                            # production: meaning → produce the English word (default, speaking practice)
book2anki mybook.epub --vocab --level C1 --lang ru --vocab-mode recognition   # English → meaning

# Parallel processing — faster for multi-chapter books
book2anki mybook.epub --parallel
book2anki mybook.epub --vocab --level B2 --lang ru --parallel

# Single compact deck instead of per-chapter files
book2anki mybook.epub --compact  # --flat also works

# Practice mode — programming exercise cards (katas, drills, variations)
book2anki effective_java.epub --practice
book2anki effective_java.epub --practice --depth 2   # more exercises per chapter
book2anki effective_java.epub --practice --topic "concurrency"
book2anki effective_java.epub --practice --code-lang java   # force all code in Java

# Model selection
book2anki mybook.epub --model sonnet              # Claude Sonnet (faster, cheaper)
book2anki mybook.epub --model opus                # Claude Opus via API
book2anki mybook.epub --model cli                 # Force claude CLI
book2anki mybook.epub --model cli:claude-fable-5  # Exact Claude CLI-only model
book2anki mybook.epub --model codex               # Codex CLI (uses codex exec)
book2anki mybook.epub --model gpt4o               # GPT-4o (requires OPENAI_API_KEY)
book2anki mybook.epub --model gpt5.5              # GPT-5.5 (default for OpenAI)
book2anki mybook.epub --model o3                  # OpenAI o3
book2anki mybook.epub --model o4-mini             # OpenAI o4-mini
book2anki mybook.epub --model claude-opus-5       # Any exact model ID

# Combine flags
book2anki mybook.epub --depth 0 --topic "agriculture"  # only essential ideas about agriculture
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

# Quick summary on a topic: depth 0 + topic = only the essential ideas about X
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

Book output uses per-chapter files by default for every depth, including `--depth 0`.
The combined deck contains the processed chapter set, so `--chapters 3-5` also writes one combined deck for chapters 3-5.
Use `--compact`/`--flat` for a single flat deck. `--topic` also outputs a single flat deck.

## Term cards

Decks contain two kinds of card, generated together in one run.

**Concept cards** run *name → meaning*: "What is tardive dysphoria?" → an explanation.

**Term cards** run the other way, *meaning → name*, because understanding an idea and being able to retrieve what it is called are separate skills — and the name is usually the part that goes missing. Each term card takes one of two shapes, whichever the source supports:

- **Cloze**, when the text has a sentence that actually defines the term:
  > When long-term antidepressant use itself produces a chronic, treatment-resistant depressed state, the result is `[...]`.

  The rule the generator applies is that a reader who understands the concept must be able to recover the term from the words that remain, and a reader who doesn't must not. A sentence like "Healy argues that `[...]` is a serious concern" fails that test — it only drills the sentence — so it becomes the second shape instead.
- **Reverse question**, when no self-contained defining sentence exists: "What is the term for depression caused by the long-term use of the antidepressants meant to treat it?" → "Tardive dysphoria".

How many terms qualify scales with `--depth`: at `--depth 0` only the one idea the text is built around, at `--depth 3` every named concept, law, effect, study, date, and quantity.

With `--lang`, the cloze sentence stays in the **source** language while the gloss and context line are written in your language — the hidden answer is a source-language term, so translating the sentence would destroy the card. Cloze cards are tagged `card::cloze`, so you can filter, reposition, or suspend them in Anki if you'd rather study them separately.

Prompt mode (`--prompt`) outputs a flat deck from model knowledge, asks the model for a concise deck title, and tags notes with `source::prompt`. Use it when you want standalone study material without providing a book, article, or video.

Vocabulary mode outputs a flat deck named `{Language} {Level} — {Book Title}` (e.g. `English B2 — The Great Gatsby`). Running for different chapter ranges produces files that merge into the same Anki deck on import.

`--vocab-mode` controls card direction. `production` (default) shows the native-language meaning, the English definition, and the context sentence with the target word blanked out; you must produce the English word/phrase aloud — trains active recall for speaking (etymology stays on the back so it doesn't give the word away). `recognition` flips it: it shows the English word and context and you recall the meaning — trains reading/listening. Both modes write the same deck name and share the `vocab::` tag prefix, so the "skip words already in Anki" dedup applies to either.

## How it works

1. **Parse** — EPUB chapters via TOC, PDF via heading detection, web via article extraction + `srcset` for high-res images, YouTube via transcript API
2. **Chunk** — split chapters into overlapping segments fitting the model's context window (~80% of limit minus output reserve)
3. **Generate** — each chunk → Claude (Opus via CLI or Sonnet via API) with depth/language/content-type-aware prompt; image captions included so the model can reference figures
4. **Dedup** — `SequenceMatcher`-based similarity dedup within chunks, plus term-based dedup for cloze cards; LLM consolidation pass across chapters in compact/topic modes
5. **Package** — `.apkg` via [genanki](https://github.com/kerrickstaley/genanki); per-chapter subdecks for books, flat deck for articles/topic/compact output

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

## Billing

If you use the **Claude CLI** (default when available), there is no direct API cost — usage goes through your Claude Code subscription.

When using API providers, book2anki does not print local cost estimates because provider pricing, caching, and token accounting can change or differ by account. Use the Anthropic/OpenAI billing dashboard for authoritative costs. Use `--chapters` to process specific chapters instead of the whole book.

## Features

- **EPUB, PDF, URL & YouTube** — books, web articles, or video transcripts
- **Four depth levels**: essential summary, core ideas, detailed, or comprehensive
- **Term cards** — alongside the usual concept cards, every deck gets cards that run *meaning → name*, so you can retrieve a term and not just recognise it. Cloze-deleted from a defining sentence in the book where one exists, otherwise a reverse question. See [Term cards](#term-cards)
- **Prompt mode** (`--prompt "..."`) — generate standalone cards from a study request using model knowledge, without a source file or URL
- **Practice mode** (`--practice`) — generate "Implement …" programming exercise cards from a book. Each card has a precise specification as the question and complete, production-ready code as the answer. Where practical, answers include runnable demonstrations; for Java this means a complete Java 17+ example with `public static void main(String[] args)`, including realistic usage and important edge cases. Solutions use proper concurrency primitives, idiomatic patterns, and correct error handling — not textbook simplifications. Use `--code-lang java` to force a specific language
- **Vocabulary mode** (`--vocab --level B2 --lang ru`) — extract words/phrases above your CEFR level with IPA pronunciation, etymology, example sentences, and translation
- **Speaking practice** (`--vocab-mode production`, the default) — production cards prompt in your native language (plus the English definition) with the word gapped out of its context, so you actively recall and say the English word instead of just recognizing it
- **Anki-aware dedup** — reads your existing Anki collection to skip words you already have
- **Topic filter** (`--topic`) — generate cards only about a specific subject (works with both regular and vocab modes)
- **Images** — extracts figures from EPUB books and web articles, includes them in relevant cards
- **Smart dedup** — similarity-based dedup within chunks; cloze cards deduped by the term they hide; LLM consolidation across chapters in compact/topic modes; vocab duplicates merged with multiple contexts
- **Dark & light theme** — cards adapt to your Anki theme
- **Parallel processing** (`--parallel`) — process multiple chapters simultaneously
- **Claude CLI support** — auto-detects `claude` CLI for subscription-based generation, falls back to API
- **Model selection** (`--model`) — choose between Sonnet (fast/cheap), Opus (highest quality), or CLI
- **Resume on interrupt**: re-run the same command and it skips already-generated chapters
- **Auto language detection** with `--lang` override
- **Progress bar** with per-chapter card counts and elapsed time
