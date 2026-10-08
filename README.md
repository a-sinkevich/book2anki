# book2anki

Turn books (EPUB/PDF), web articles and YouTube videos into Anki decks, using Claude or GPT. Also extracts vocabulary for language learners.

## Quick start

**1. Download** the binary for your platform from [Releases](https://github.com/a-sinkevich/book2anki/releases/latest):
`book2anki-macos-arm64` · `book2anki-linux-amd64` · `book2anki-windows-amd64.exe`

**2. Set up a provider** — one of:

| Provider | Setup |
|---|---|
| **Claude CLI** (recommended) | Nothing. If you have [Claude Code](https://docs.anthropic.com/en/docs/claude-code), book2anki finds it and uses Opus through your subscription. |
| **Anthropic API** | [Get a key](https://console.anthropic.com/settings/keys), [add credit](https://console.anthropic.com/settings/billing), put `ANTHROPIC_API_KEY=your-key` in `~/.book2anki.env` |
| **OpenAI API** | [Get a key](https://platform.openai.com/api-keys), put `OPENAI_API_KEY=your-key` in `~/.book2anki.env`, then use `--model gpt5.5` |

On Windows the env file is `C:\Users\<YourName>\.book2anki.env`.

**3. Make it executable** (macOS/Linux, once):

```bash
chmod +x book2anki-macos-arm64
```

> **macOS**: if you see "cannot be opened because the developer cannot be verified", run
> `xattr -d com.apple.quarantine book2anki-macos-arm64`

**4. Run:**

```bash
./book2anki-macos-arm64 mybook.epub
./book2anki-macos-arm64 mybook.pdf --depth 2
./book2anki-macos-arm64 "https://en.wikipedia.org/wiki/Spaced_repetition"
./book2anki-macos-arm64 "https://www.youtube.com/watch?v=lrSB9gEUJEQ"
./book2anki-macos-arm64 --prompt "Cognitive load theory for software engineers"
```

## From source

Requires **Python 3.10+**.

```bash
git clone https://github.com/a-sinkevich/book2anki.git
cd book2anki
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
python -m book2anki mybook.epub
```

Examples below write `book2anki`; substitute `./book2anki-macos-arm64` or `python -m book2anki`.

## Options

| Flag | What it does |
|---|---|
| `--depth 0..2` | 0 = essential summary, 1 = core ideas *(default)*, 2 = enough to discuss the book fluently |
| `--chapters` | `3`, `1,3,5`, `3-7`, `1,3-5,8` (1-based) |
| `--lang ru` | Write cards in another language than the source (default: auto-detect) |
| `--topic "dopamine"` | Only cards about one subject |
| `--flat` / `--compact` | One deck file instead of per-chapter files |
| `--parallel` | Process chapters simultaneously |
| `--output DIR` | Output directory (default: `<BookTitle>/`) |
| `--prompt "..."` | Generate from a study request, no source file |
| `--vocab --level B2` | Vocabulary mode (see below); add `--audio` for pronunciation |
| `--practice` | Programming exercise cards (see below) |
| `--idioms` | Interview drill cards: code idioms typed from memory (see below) |
| `--model` | See [Models](#models) |

```bash
book2anki mybook.epub --depth 0                       # just the key takeaways
book2anki mybook.epub --chapters 1,3-5 --lang ru
book2anki VIDEO_ID --depth 2                          # bare YouTube ID works too
book2anki sapiens.epub --topic "agriculture"          # pull one thread from a broad book
book2anki neuroscience.epub --depth 0 --topic "synaptic plasticity"
```

URLs need quotes so the shell doesn't mangle them.

## Card types

Every deck contains two kinds of card, generated together in one run; programming books get a third, [command cards](#command-cards).

**Concept cards** ask about an idea: *"Why is Avro friendlier for dynamically generated schemas?"* → an explanation.

**Production cards** run the other way — they make you retrieve the piece a concept card would hand you in its question. Two things qualify:

- a **name**, because understanding an idea and recalling what it's called are separate skills;
- a **distinguishing property** (`--depth 2` only), the specific thing a claim turns on — which case a technique suits, what separates two approaches, when a result holds.

A **name** is always asked as a reverse question: *"What is the term for depression caused by the long-term use of the antidepressants meant to treat it?"* → *"Tardive dysphoria"*. A sentence defining a term almost always opens with it, so clozing the name puts the gap first and makes you hold the whole sentence in your head before you can fill it.

A **property** becomes a cloze when the book has a sentence that ends on it:

> The difference is that Avro is friendlier to `[...]` schemas.

and a reverse question otherwise. The test a cloze must pass: a reader who understands the material recovers the hidden words, and a reader who doesn't can't guess them.

**Cloze sentences are always quoted from the book, never composed.** The model may resolve a pronoun, drop a pointer like "described earlier", or drop a trailing clause so the sentence stands alone; nothing more. YouTube transcripts get reverse questions only — a speech-to-text transcript is a machine's guess at what was said, so quoting it would bake transcription errors into your cards.

How many qualify scales with `--depth`: at 0, only the one idea the text is built around; at 2, the terminology you would be expected to recognise in conversation about the book.

With `--lang`, a cloze sentence stays in the **source** language while the gloss and context line are written in yours — the hidden answer is source-language wording, so translating the sentence would destroy the card. Cloze cards use their own note type, so `note:"book2anki Cloze"` selects them as a group in the Anki browser.

### Command cards

Programming books also get cards you answer by **typing**, for the commands and one-liners worth knowing by heart: *"(git) Show the last 3 commits, one line each"* → you type `git log --oneline -3`, and Anki shows your line against the answer character by character. The question uses real values rather than placeholders, so there's one line to type. The answer is the spelling most people would use, and the back explains each flag and lists other valid forms, so a different but correct answer is easy to recognise. You still grade yourself.

They're for lines you'd type again and again, not one-off setup or anything longer than a line (`--practice` covers real code). There are none at `--depth 0`; at 1 you get the commands a chapter is built around, and at 2 also the everyday flags and variants it shows. Command cards use the `book2anki Typed` note type and carry the `kind::command` tag.

## Vocabulary mode

Extracts words and phrases above your CEFR level, with IPA, etymology, translation and an example sentence.

```bash
book2anki mybook.epub --vocab --level B2 --lang ru
book2anki mybook.epub --vocab --level C1 --lang ru --topic "medicine"
book2anki "https://example.com/article" --vocab --level C1 --lang ru
```

`--vocab-mode` sets the direction:

- **`auto`** (default) — the model decides per word. A word you would use yourself, formal ones included (*ubiquitous*, *to come to grips with*), gets a production card; an archaic, literary or rare word, or narrow jargon (*susurrus*, *betwixt*), gets a recognition card only — you need to understand it on the page, and drilling yourself to say it would train a skill you'll never use. Recognition-only words show their register (*literary*, *archaic*…) under the word and are tagged `usage::passive` (the rest `usage::active`), so you can filter them in the Anki browser.
- **`production`** — every word as a production card: the meaning in your language plus the context sentence with the word gapped out; you say the English word. Trains speaking; etymology stays on the back so it doesn't give the answer away.
- **`recognition`** — every word as a recognition card: the English word, you recall the meaning. Trains reading and listening.

Decks are named `{Language} {Level} — {Book Title}`, so separate chapter ranges merge into one deck on import. book2anki also reads your existing Anki collection and skips words you already have.

### Pronunciation audio

`--audio` puts a small play button next to the IPA; it plays only when you click it.

```bash
book2anki mybook.epub --vocab --level C1 --lang ru --audio
```

With an OpenAI key, every word is synthesised by OpenAI's speech model (`gpt-4o-mini-tts`), so the whole deck is one voice. It knows how rare words are said rather than guessing from spelling, and is shown the book's sentence so a word with several pronunciations (*record*, *lead*) comes out as the book meant it. English is British throughout: the speech model is asked for Received Pronunciation, and British recordings are picked first. Clips are cached in `~/.cache/book2anki/audio`, so a re-run only fetches what's missing.

Without a key, or for a word OpenAI fails on, a word gets a real speaker's recording from Wiktionary when there is one. Words with several pronunciations always skip Wiktionary, since a recording can't say which one the book meant.

To get the key — the same one as `--model gpt5.5`, even if the cards themselves come from Claude:

1. [Create a key](https://platform.openai.com/api-keys) and [add a little credit](https://platform.openai.com/settings/organization/billing). A book's vocabulary costs cents.
2. Put it in `~/.book2anki.env`:

   ```
   OPENAI_API_KEY=your-key
   ```

Without a key, words with no recording — most phrases and a lot of jargon — just get no audio. `OPENAI_TTS_VOICE` picks another [voice](https://platform.openai.com/docs/guides/text-to-speech) (default `marin`).

## Practice mode

Programming exercise cards instead of theory: a precise "Implement …" spec as the question, complete production-ready code as the answer — proper concurrency primitives, idiomatic patterns, real error handling. Where practical the answer runs as-is; for Java that means a full Java 17+ example with `main`, realistic usage and edge cases.

```bash
book2anki effective_java.epub --practice
book2anki effective_java.epub --practice --depth 2 --topic "concurrency"
book2anki effective_java.epub --practice --code-lang java
```

## Idioms mode

Drill cards for interview prep: the small idioms you should write without pausing — `lock()` / `try` / `finally unlock()`, `wait()` in a `while` loop, shutting an executor down with a deadline, `computeIfAbsent`. A separate deck, like practice mode, named `Idioms | {Book}`.

```bash
book2anki java_concurrency.epub --idioms
book2anki java_concurrency.epub --idioms --depth 2 --code-lang java
```

Most of these idioms span several lines, so the main card is a short snippet with its key piece hidden. You **type** the missing piece, and Anki checks it character by character:

```java
synchronized (lock) {
    [...] {          // you type: while (!ready)
        lock.wait();
    }
    consume();
}
```

The code around the gap fixes every name the answer uses, so a correct answer only has one way to be written. The back gives the reason for the idiom's shape in one line ("a loop, never an if: wait() can wake spuriously"), since interviewers ask why as well as how, plus the common mistake or the old form. A snippet with two pieces worth drilling becomes two cards. Where the question can name every variable, a card asks for a whole line instead: *"Given `Map<String, List<Integer>> index`, append `n` under `key`…"* → `index.computeIfAbsent(key, k -> new ArrayList<>()).add(n);`.

A card is only made for an idiom an interviewer would expect you to write from memory, not syntax every developer knows or classes from the book's sample code. Idioms are written in the modern form of the language (Java 21+) even when the book is older; the old form is mentioned on the back. `--code-lang` drills the same idioms in another language. The cards use the `book2anki Typed Cloze` and `book2anki Typed` note types and carry the `kind::idiom` tag.

## Models

Default: the `claude` CLI with Opus if it's installed, otherwise the Anthropic API.

```bash
book2anki mybook.epub --model sonnet              # faster, cheaper
book2anki mybook.epub --model opus                # CLI if available, else API
book2anki mybook.epub --model cli                 # force the Claude CLI
book2anki mybook.epub --model cli:claude-fable-5  # exact CLI-only model
book2anki mybook.epub --model codex               # Codex CLI
book2anki mybook.epub --model gpt5.5              # OpenAI (also gpt4o, o3, o4-mini)
book2anki mybook.epub --model claude-opus-5       # any exact API model ID
```

## Output

```
Book-Title/
  Book-Title.apkg           # combined deck
  chapters/
    01 - chapter-name.apkg  # per-chapter decks
    media/                  # figures, when the book has them
```

Books get per-chapter files at every depth. The combined deck holds whichever chapters you processed, so `--chapters 3-5` also writes a combined deck of 3–5. `--flat`/`--compact` and `--topic` write a single deck instead.

Each chapter is saved as it finishes, so you can interrupt a run and re-issue the same command to pick up where it stopped.

## How it works

1. **Parse** — EPUB by TOC, PDF by heading detection, web by article extraction (with `srcset` for high-res images), YouTube by transcript API. Figures are extracted with their captions, and the author's own italic and bold survive into the text as a signal for which words a sentence turns on.
2. **Chunk** — split long chapters into overlapping segments that fit the model's context window.
3. **Generate** — each chunk goes to the model with a prompt shaped by depth, language and content type.
4. **Dedup** — every chapter is deduplicated: near-identical questions by similarity, cloze cards by the span they hide, and a cloze is dropped when it only restates a reverse question already covering the same fact. Compact and topic modes add an LLM consolidation pass across chapters.
5. **Package** — `.apkg` via [genanki](https://github.com/kerrickstaley/genanki), per-chapter subdecks for books, one flat deck otherwise. Cards follow your Anki light/dark theme.

## Development

```bash
pip install -e ".[dev]" build

make check       # lint + typecheck + tests
make build       # check + build wheel/sdist
make clean
```

Or individually: `python -m flake8 book2anki/ tests/`, `python -m mypy book2anki/`, `python -m pytest tests/ -v`.

## Billing

With the **Claude CLI** there's no API cost — it goes through your Claude Code subscription.

With API providers, book2anki deliberately prints no cost estimate: pricing, caching and token accounting change and differ by account, so any local number would be a guess. Check your Anthropic or OpenAI dashboard. Use `--chapters` to try a few chapters before committing to a whole book.
