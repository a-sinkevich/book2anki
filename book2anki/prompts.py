import re

DEPTH_INSTRUCTIONS = {
    0: (
        "Generate cards only for the single most important ideas worth remembering long-term: "
        "the main thesis, core mental model, or essential conclusion. "
        "Do not aim for a fixed number of cards; create as many or as few as the content warrants, "
        "including zero for sections without substantive ideas. This is a minimal summary, not a study guide."
    ),
    1: (
        "Generate cards that test understanding of the chapter's core ideas: "
        "the main thesis, key arguments, and central takeaways. "
        "Leave out supporting evidence, examples, distinctions and secondary arguments — "
        "including the important ones, which belong to a more detailed pass — and never "
        "add a card merely because the chapter names or mentions something. "
        "Let the material decide how many cards that is: a dense chapter genuinely has "
        "more core ideas than a thin one. But every card must be one of those ideas, "
        "not a detail that arrived alongside one."
    ),
    2: (
        "Generate the cards that would leave a reader able to hold their own in a conversation "
        "about this text with someone else who has read it: to state its argument, use its "
        "vocabulary, and give the reasoning behind its main claims — without notes. "
        "THE TEST for every card: would not knowing this leave you unable to follow or take part "
        "in that conversation? "
        "That takes the core ideas, the terms they go by, the distinctions the argument turns on, "
        "and the evidence or trade-offs it rests on. "
        "It does not take what would never come up: the fine mechanics of how something works, "
        "figures and dates unless the number is itself the point, the full roster of names, "
        "works or products where one or two carry the idea, and asides about history or "
        "provenance. "
        "This is the most detailed level — there is no more thorough pass to defer to — so judge "
        "each card by the test above rather than saving it for one. "
        "Where the text lays out the alternative ways of doing something, the set is an idea in "
        "its own right: cover what the options are and what separates them, even where one option "
        "is thin taken alone. Where it also names who or what is used for each — tools, works, "
        "schools of thought, the people associated with them — those names earn ONE further card "
        "for the whole set, asking which is used for which, with the names in the ANSWER and never "
        "in the question. Being able to say what people actually reach for is half of knowing a "
        "field, and a name you are handed in the question is a name you never have to recall. One "
        "card for the set, never a card per option and never one per name. Names carrying no "
        "weight are left out of it: ones any reader would know without this text, and ones the "
        "text drops in passing."
    ),
}

# How many terms are worth recalling *by name* at each depth. Depth 0 is a
# minimal summary, so it earns a term card only for the one idea the section is
# built around.
TERM_DEPTH_INSTRUCTIONS = {
    0: (
        "Only if the single central idea of this text has a proper name, add one term card "
        "for that name. Otherwise add none."
    ),
    1: (
        "Add term cards only for names central to the text's argument — the terms a reader "
        "would need to use to discuss it. Skip passing jargon."
    ),
    2: (
        "Add term cards for the central names plus the secondary terminology, named studies "
        "and effects a reader would be expected to recognise in conversation. Skip a name "
        "nobody would use out loud."
    ),
}


# Distinguishing properties are supporting material by the depth ladder — depth 1
# is told in so many words to leave distinctions out — so these cards start at
# depth 2, where the concept cards covering the same material start. An empty
# string drops the whole category from the prompt.
PROPERTY_DEPTH_INSTRUCTIONS = {
    0: "",
    1: "",
    2: (
        "Add property cards for the distinctions the argument turns on: what separates two "
        "things it compares, and the conditions it gives for when a claim holds. Skip "
        "distinctions the text draws only in passing."
    ),
}


# Command cards are for programming books only. A minimal summary has no room
# for syntax, so they start at depth 1, with the commands the chapter is about.
COMMAND_DEPTH_INSTRUCTIONS = {
    0: "",
    1: (
        "Add command cards only for the commands the text is built around — the ones a "
        "reader would come away from it using."
    ),
    2: (
        "Add command cards for every command the text teaches that a practitioner would "
        "reach for again: the central ones, plus the flags and variants it shows for "
        "everyday tasks."
    ),
}

_COMMAND_EXAMPLE = (
    '  {"type": "command", "question": "(git) Show the last 3 commits, one line each", '
    '"answer": "git log --oneline -3", "example": "<pre><code>--oneline  abbreviated hash '
    'and subject\\n-3         only the last 3 commits</code></pre>Also valid: '
    '<code>git log --oneline -n 3</code>"},\n'
)


def _command_cards_section(depth: int) -> str:
    """Instructions for cards the reader answers by typing a command.

    Anki compares the typing with the answer character by character, which
    only works for a single line with one canonical spelling — so the rules
    are mostly about making the answer exactly that, and pushing everything
    else (flag breakdown, equivalent forms) into the example.
    """
    depth_instruction = COMMAND_DEPTH_INSTRUCTIONS[depth]
    if not depth_instruction:
        return ""
    # Outside the f-string: a backslash in an f-string expression is a syntax
    # error before Python 3.12.
    example = _COMMAND_EXAMPLE.rstrip(",\n")
    return f"""

**Command cards — for the lines a practitioner types from memory.** Some of what a \
programming book teaches is meant to be typed, not looked up: a shell or CLI invocation, a \
one-line idiom, a short API call. For those the reader should practise producing the line \
itself, so the card is answered by typing it. This is the one kind of card that asks for \
syntax. {depth_instruction} Set "type": "command". The question states a concrete task and \
names the tool; the answer is the exact line that does it.

- **One line, exactly as typed**: plain text, with no HTML, no <code>, no bold, no prompt \
sign such as $, and no explanation. The reader's typing is compared with the answer \
character by character, so anything extra marks a correct answer wrong
- **Concrete values, so there is one answer**: put real values in the question ("the last \
3 commits", "port 8000") and never a placeholder such as <branch> or N in the answer
- **The canonical spelling**: the form most practitioners would type — the usual flag \
order, short flags where those are the norm. Put a breakdown of the flags and any \
equivalent forms in "example", with <pre><code>...</code></pre> for code, so a reader \
who typed a valid variant can see that it was valid
- **Only lines worth having in your fingers**: skip one-off setup, commands tied to the \
book's own sample project, and anything that does not fit on one line — a regular card \
covers those. When the text teaches no commands, add none
- **One card per command**: a regular card asking which command or option does the task \
("How do you…", "Which option…") asks for the same thing — leave it out. A card asking \
what an option does or why you would use it runs the other way, and stays

{example}"""


_REVERSE_FORM_BODY = """Set "type": "term". The question describes everything \
except the missing piece; the answer is that piece and nothing else.

  {"type": "term", "question": "What is the term for depression caused by the long-term \
use of the antidepressants meant to treat it?", "answer": "Tardive dysphoria"}"""

_REVERSE_PROPERTY_EXAMPLE = """
  {"type": "term", "question": "Sparse indexes save memory over dense ones — at the \
cost of what?", "answer": "A short scan of the segment after the nearest indexed key"}"""


_NAME_IS_NEVER_A_CLOZE = """  Never cloze a name. The sentence that defines a term almost always opens with it, \
so the gap comes first and the reader has to hold the whole sentence around it before \
they can fill it — work for short-term memory that teaches nothing. A question describes \
the thing first and asks for its name last, which is the order it is recalled in.

  Not: "A {{c1::predicate lock}} works similarly to the shared/exclusive lock described \
earlier, but it belongs to all objects that match a search condition."
  But: {"type": "term", "question": "What is the term for a lock that belongs to all \
objects matching a search condition, rather than to one particular object?", \
"answer": "Predicate lock"}"""


def _term_cards_section(
    depth: int, language: str, quote_source: bool = True,
) -> str:
    """Instructions for production-direction cards: retrieve, don't recognise.

    The cards produced by the main instructions run question → answer, and they
    routinely name the retrievable part inside the question. These run the other
    way: given everything else, produce the missing piece. Two kinds of piece
    qualify — a name, and (from depth 2) the property a claim turns on. Both
    directions have to be trained separately: understanding an idea perfectly is
    no guarantee of being able to retrieve what it is called or what it hinges on.

    A name is always asked as a reverse question: the defining sentence opens
    with the term, so clozing it puts the gap first. Only a property may be a
    cloze, and only where the gap ends the sentence — so below depth 2 there
    are no clozes at all. Cloze cards quote the source verbatim, so
    `quote_source` is False for sources that are not authored prose
    (speech-to-text transcripts): those get reverse questions only, rather
    than cards built on a machine transcription.
    """
    property_depth = PROPERTY_DEPTH_INSTRUCTIONS[depth]
    if quote_source and property_depth:
        forms = f"""The missing piece decides the form:

**A name — always a reverse question.** {_REVERSE_FORM_BODY}

{_NAME_IS_NEVER_A_CLOZE}

**A property — a cloze when the gap ends the sentence, a reverse question otherwise.** \
For a cloze, set "type": "cloze". Take a sentence from the source text above — quote it, \
never compose one — wrap the missing piece in {{{{c1::...}}}}, and put a one-line gloss in \
"answer". The gap must close the sentence, or be followed only by a word or two that do \
nothing to recover it: the reader then reaches it having read everything that pins it \
down. A gap earlier in the sentence is the same burden as a clozed name — ask a reverse \
question instead.

  THE TEST every cloze must pass: a reader who understands the material but has \
forgotten this particular piece must be able to recover it from the words that remain — \
and a reader who does not understand the material must not be able to guess it. If the \
rest of the sentence does not pin the answer down, the card only teaches the sentence. \
Ask a reverse question instead.

  Passes: "You may add or remove only a field that has {{{{c1::a default value}}}}." \
(the gap closes the sentence)
  Fails:  "Only {{{{c1::a field with a default value}}}} may be added or removed." (the \
same fact, but the gap opens the sentence — ask which fields may be added or removed \
instead)

  A property as a reverse question:{_REVERSE_PROPERTY_EXAMPLE}"""

        cloze_rules = f"""
- **Never write the sentence yourself.** The cloze sentence is always the author's own, \
copied from the source text above. You may resolve a pronoun or back-reference so it \
stands alone ("it" → the thing itself, "this approach" → the named approach), drop a \
pointer to elsewhere in the text ("described earlier", "as we saw in Chapter 3") — the \
card will be reviewed without it — and drop a trailing clause that depends on earlier \
text. Nothing beyond that: no rephrasing, no stitching two sentences together, no claims \
the text does not make, and nothing drawn from your own knowledge of the subject. If no \
sentence in the text works, ask a reverse question — never invent a sentence in order to \
make a cloze possible
- **Keep the cloze sentence in the language of the source text**, always — even though \
the other cards are written in {language}. The hidden answer IS the source's own \
wording, so translating the sentence would destroy the card. Write "answer" and \
"context" in {language}
- **Exactly one {{{{c1::...}}}} per card.** Never c2, c3, or multiple deletions. Hide the \
missing piece only, never the surrounding words that make it derivable
- **"context" field**: a short orienting phrase in {language} (3-8 words) naming what \
the sentence is about, for sentences that read as ambiguous on their own. It must NEVER \
contain the hidden words or a translation of them, or the card gives itself away. Leave \
it empty when the sentence already stands alone
- **Answer side of a cloze**: a one-line gloss in {language}. Do not restate the whole \
sentence"""
    elif quote_source:
        forms = f"""Use one form only:

**Reverse question.** {_REVERSE_FORM_BODY}

{_NAME_IS_NEVER_A_CLOZE}"""

        cloze_rules = ""
    else:
        forms = f"""This source is a speech-to-text transcript rather than authored prose, so it \
holds no wording worth quoting verbatim. Use one form only:

**Reverse question.** {_REVERSE_FORM_BODY}

Do NOT emit any card with "type": "cloze" for this source, and do not write a sentence \
of your own to cloze — a transcript's phrasing is a machine's approximation of what was \
said, and quoting it would bake transcription errors into the answer."""

        cloze_rules = ""

    return f"""

PRODUCTION CARDS (second card type — retrieve it, don't just recognise it)

The cards described above hand you the answer's subject inside the question. Also \
generate cards for the other direction: given everything else, produce the missing \
piece. Recognising something and retrieving it are separate skills, and the retrievable \
part is the one that goes missing.

{_targets_section(property_depth)}

These are an ADDITION to the cards above and change nothing about them. The depth \
instruction alone decides how many of those to write — adding production cards is not a \
reason to write more. In particular: never add a concept card so that a production card \
has something to pair with, do not give every concept a name card, and do not give \
every emphasised phrase a property card.

{TERM_DEPTH_INSTRUCTIONS[depth]}{f" {property_depth}" if property_depth else ""}

{forms}

Rules for production cards:{cloze_rules}
- **A reverse question is written in {language}, but a name in its answer keeps the \
source's own spelling** — do not translate the term itself
- **One card per missing piece.** Do not build several cards testing the same name or \
the same property
- **Only what is worth retrieving.** A name card earns its place when the name is the \
thing you would forget. Skip everyday words, and skip terms the text merely mentions \
without explaining{_property_rules(property_depth, quote_source)}"""


def _targets_section(property_depth: str) -> str:
    """The kinds of missing piece a production card may test."""
    name_target = """Exactly one kind of missing piece qualifies, and nothing else does:

  A NAME — what the thing is called."""
    if not property_depth:
        return name_target
    return """Exactly two kinds of missing piece qualify, and nothing else does:

  1. A NAME — what the thing is called.
  2. A DISTINGUISHING PROPERTY — the specific thing a claim turns on: which case a \
technique suits, what separates two approaches the text compares, the condition under \
which a result holds."""


def _property_rules(property_depth: str, quote_source: bool) -> str:
    """Eligibility rules that keep property cards from swallowing every sentence.

    The two rules about the deleted span and about `<em>` only apply where cloze
    is on the table and the source carries markup — that is, not to transcripts.
    """
    if not property_depth:
        return ""
    rules = """
- **A property card needs a contrast or a condition.** The sentence has to separate \
this from that, or say when something holds. A sentence that merely states an idea, \
however important, holds no property card — stating ideas is what the cards above are \
for
- **But a sentence naming BOTH sides of a contrast is not a cloze.** Where the text sets \
two named things against each other and says what each one does, hiding either side \
hands the reader the other, and the card can be answered by elimination or by \
recognising the sentence. Write an ordinary question asking for the difference instead, \
so both halves have to be produced — that is also the form the knowledge gets used in. \
Cloze only where the sentence states one side, leaving no second half to give away

  Cloze: "Avro is friendlier to {{c1::dynamically generated}} schemas." (one side \
stated — nothing is handed over)
  Ask:   "2PL provides serializable isolation, whereas 2PC provides atomic commit." \
→ both sides named, so write "What is the difference between 2PL and 2PC?" instead of \
clozing either half
- **Drop anything you could not grade.** If a reader could answer defensibly in several \
ways and the sentence does not force one of them, there is no card. A name has one \
right answer; a property only sometimes does, and the ones that do not are worse than \
nothing

  Passes: "You may add or remove only a field that has {{c1::a default value}}." (a \
condition with one right answer)
  Fails:  "You can think of storing something in the database as {{c1::sending a \
message to your future self}}." (a metaphor has no single right wording — a reader who \
understands the point perfectly still cannot reproduce that phrase, so the card marks \
them wrong for knowing it)"""
    if not quote_source:
        return rules
    return rules + """
- **Hide a phrase, not a clause.** The deletion is a noun phrase or a qualifier: a few \
words. If you find yourself deleting half a sentence, there is no card here — that is \
transcription, not recall
- **Author emphasis is a hint, not a licence.** Where the source marks a phrase with \
<em> or <strong> — books use italic and bold for the same job — that is often exactly \
the span a property card should hide, and it is the best clue available. But the same \
markup also marks a term at its first use, a merely stressed word, and placeholders \
inside code — and most emphasised phrases earn no card at all"""


_CODE_INDICATORS = re.compile(
    r"(?:"
    r"(?:^|\n)\s*(?:def |class |import |from .+ import |public |private |protected |void |int |return )"
    r"|(?:^|\n)\s*(?:if\s*\(|for\s*\(|while\s*\(|switch\s*\()"
    r"|\b(?:nullptr|NULL|this->|self\.|\.getInstance|@Override|@Test)"
    r"|\b(?:function\s+\w+\s*\(|const\s+\w+\s*=|=>\s*\{)"
    r"|(?:^|\n)\s*(?:#include|#define|#ifdef)"
    r"|(?:\{\s*\n.*\n\s*\})"
    # A shell session or REPL: books on git, Docker or the command line show
    # few braces but many prompts. A lowercase command after "$ " keeps a price
    # on a wrapped PDF line ("$ 20") from counting.
    r"|(?:^|\n)[ \t]*(?:\$ [a-z]|>>> )"
    r")",
    re.MULTILINE,
)


def detect_programming(text: str) -> bool:
    """Heuristic: is this text from a programming book?"""
    sample = text[:30000]
    hits = len(_CODE_INDICATORS.findall(sample))
    return hits >= 5


def _format_figures_section(
    captions: list[tuple[str, str]] | None,
) -> str:
    """Format book figures as a numbered list for the prompt."""
    if not captions:
        return ""
    lines = ["Available figures from the book (reference by ID in the image field):"]
    for img_id, caption in captions:
        lines.append(f"  [{img_id.upper()}] {caption}")
    return "\n".join(lines) + "\n\n"


def build_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    language: str,
    is_article: bool = False,
    is_programming: bool = False,
    book_image_captions: list[tuple[str, str]] | None = None,
    topic: str = "",
    is_transcript: bool = False,
) -> str:
    depth_instruction = DEPTH_INSTRUCTIONS[depth]

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Generate cards ONLY about: {topic}. "
            "Skip everything unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    if is_article:
        source_header = f'Article: "{book_title}"'
        context_rule = (
            "- **Make questions self-contained**: cards are reviewed mixed with other decks, "
            "so include enough topic context in each question that the reader knows what domain "
            "it belongs to. Never say \"the article\", \"the author\", \"this section\" — "
            "use specific names, concepts, or topic references instead"
        )
        text_label = "Article text"
    else:
        source_header = f'Book: "{book_title}"\nChapter: "{chapter_title}"'
        context_rule = (
            "- **Make questions self-contained**: never say \"the chapter\", \"the author\", "
            "\"this section\" — use specific names, concepts, or book title instead. "
            "Cards are reviewed out of context"
        )
        text_label = "Chapter text"

    example_rule = (
        '\n- **Example field**: make cards usable as standalone learning material, not just memory prompts. '
        'For every non-trivial concept, fill the "example" field with a concrete example, scenario, '
        "counterexample, common gotcha, misconception, vivid analogy, or connection to another concept. "
        "Draw from both the book's own examples and your broader knowledge when that helps clarify the idea. "
        'Leave "example" as an empty string only for atomic facts where an example would add no value'
    )

    programming_rules = ""
    if is_programming:
        programming_rules = """
- **Focus on "why" and "when"**: prefer cards like "When would you use X?" or "What problem does X solve?" over "What is the syntax for X?"
- **Technique cards**: for named techniques/patterns/refactorings, test: (1) what problem it solves, (2) how it works, (3) when to apply it
- **Trade-off cards**: when the text compares approaches, create cards that test understanding of trade-offs
- **No trivial syntax cards**: don't create cards for basic language syntax that any developer would know"""
        example_rule = (
            '\n- **Example field**: make cards usable as standalone learning material, not just memory prompts. '
            'For every non-trivial programming concept, idiom, API, pattern, or concurrency rule, fill the '
            '"example" field with a minimal code snippet, concrete scenario, counterexample, common gotcha, '
            "real-world failure mode, or connection to related concepts. Use <pre><code>...</code></pre> "
            "for code snippets. Draw from both the book's own examples and your broader knowledge when that "
            'helps clarify the idea. Leave "example" as an empty string only for atomic facts where an example '
            "would add no value"
        )

    has_book_images = bool(book_image_captions)

    image_rule = ""
    if has_book_images:
        image_rule = (
            '\n- **Image field**: include an optional "image" field. '
            "If one of the available book figures matches the card's concept, "
            f"reference it by writing its ID followed by a short caption in {language} "
            "(e.g. \"[BOOK-IMG-1] short description of the figure\"). "
            f"The caption after the ID is REQUIRED and must be in {language}. "
            "Prefer using book figures when they help understand the concept visually. "
            'Leave "image" as empty string when not needed'
        )

    code_format_note = ""
    if is_programming:
        code_format_note = (
            "\n\nIMPORTANT: All fields are rendered as HTML. For code snippets use "
            "<pre><code>...</code></pre> tags."
        )

    redundancy_rule = ""
    if depth >= 2:
        redundancy_rule = (
            "\n- **Test key concepts from multiple angles**: for important ideas, "
            "add both a definition card and an application card"
        )

    term_section = _term_cards_section(
        depth, language, quote_source=not is_transcript,
    )
    command_section = _command_cards_section(depth) if is_programming else ""
    command_example = _COMMAND_EXAMPLE if command_section else ""
    if command_section:
        code_format_note += (
            " The one exception is a command card's answer: the plain line, as typed."
        )
    cloze_example = ""
    if PROPERTY_DEPTH_INSTRUCTIONS[depth] and not is_transcript:
        cloze_example = (
            '  {"type": "cloze", "question": "A sentence from the text ending in the '
            'property it turns on, replaced by {{c1::the property}}.", '
            f'"answer": "One-line gloss in {language}.", "context": "short orienting phrase"}},\n'
        )

    return f"""You are an expert at creating Anki flashcards from {"articles" if is_article else "books"}.

{source_header}
Language: {language}

{depth_instruction}{topic_instruction}

Guidelines:
- **Minimum information principle**: one idea per card. Prefer splitting long lists into separate cards over bundling them into one answer
- **Mix question types**: factual recall, conceptual understanding, and application
- **Write cards in {language}**
- **No trivial cards**: every card should test something genuinely worth remembering
- **No meta-cards**: never create cards about the book's structure, what a chapter covers, the author's approach, or how the book is organized. Only test the actual subject matter — the ideas, facts, and concepts themselves. If a chapter is mostly introductory or structural with little substantive content, generate fewer cards
{context_rule}
- **Disambiguate confusable concepts**: highlight the distinguishing feature when similar terms or processes appear
- **Add a domain label**: if a term is ambiguous across fields, prefix the question — e.g. "(genetics) What is GRE?"
- **Build on fundamentals**: include prerequisite concepts in the question rather than assuming prior cards
- **Logical order**: arrange cards so foundational concepts come first — definitions before applications, causes before effects
- **Answers should be concise but complete** — typically 1-3 sentences
- **Lists in answers**: when an answer contains a numbered or bulleted list, use <br> between items for readability
- **Bold the gist of every answer**, with <b>...</b>. The reader turns the card over to check what they recalled, and one who got it right should be able to confirm it at a glance instead of re-reading the answer. That only works if the bold is always there: a reader learns to look at the bold first, and every answer left bare sends them back to reading the whole thing. The one exception is an answer that is already its own gist — a term, a name, a number, or a phrase of a few words taken in at one glance — where bold would mark everything and so nothing
- **Choose the span by a test, not by what looks important.** THE TEST: cut the bolded words out, and the answer should stop answering the question; read on their own, they should be enough for a reader who recalled the answer to confirm it. That is usually a phrase rather than a single noun — a few words, never most of the answer — and it is never a word the question already contains: the reader was handed that word, not asked for it. One span for a one-part answer. Where an answer has parallel parts — a list, or the two sides of a contrast — put one span in each part, chosen by the same test, and mark every part or none: marking one side of a comparison and leaving the other bare is worse than marking neither
- **Bold belongs in the answer only**: never in a question, never in the "example" field, and never in a cloze card, where Anki already highlights the revealed words

  Passes: "Each leader accepts writes locally <b>without waiting for the others</b>, then propagates its changes asynchronously."
  Fails:  "Each <b>leader</b> accepts writes locally without waiting for the others." (the question already said leader — the reader had to supply every word except that one)
  Fails:  "<b>Each leader accepts writes locally without waiting for the others</b>, then propagates its changes asynchronously." (most of the answer is bold, so the eye has nothing to land on)
  Passes: "With synchronous replication the leader <b>waits for the follower to confirm</b> before reporting success; with asynchronous replication it <b>sends the change without waiting</b>."
  Fails:  "With <b>synchronous</b> replication the leader waits for the follower to confirm; with asynchronous replication it sends the change without waiting." (both names came from the question, and only one side of the contrast is marked)
- **No italics, ever**: do not use <em>, <i>, or any italic formatting. Where the source text below carries <em> or <strong>, that is the author's own emphasis, preserved so you can see which words they stressed — it is information for you, not markup to copy. Strip it from everything you write, a quoted cloze sentence included, or the author's emphasis ends up sitting on your deletion{programming_rules}{redundancy_rule}{example_rule}{image_rule}
{term_section}{command_section}

{_format_figures_section(book_image_captions)}Output ONLY a JSON array of objects with "question", "answer", and optionally "example", "type" and "context"{' and "image"' if has_book_images else ''} fields. Every kind of card goes in the SAME array; where a term card happens to relate to one of the cards above, place it directly after that card. No markdown, no explanation, no wrapper — just the raw JSON array.{code_format_note}

Example format:
[
  {{"question": "What is X?", "answer": "X is...", "example": ""{', "image": ""' if has_book_images else ''}}},
  {{"question": "Why does Y happen?", "answer": "Because...", "example": "For instance, when Z occurs..."{', "image": "[BOOK-IMG-1] Description of the figure"' if has_book_images else ''}}},
{cloze_example}{command_example}  {{"type": "term", "question": "What is the term for <description of the concept>?", "answer": "The term"}}
]

{text_label}:
---
{chapter_text}
---

Generate the flashcards now as a JSON array:"""


def build_prompt_request(
    request: str,
    depth: int,
    language: str,
) -> str:
    """Build a prompt for source-free study material generated from model knowledge."""
    depth_instruction = DEPTH_INSTRUCTIONS[depth]

    return f"""You are an expert teacher creating standalone Anki flashcards from a study request.

Study request:
---
{request}
---

Language: {language}

{depth_instruction}

Guidelines:
- **Use your broader knowledge** to teach the requested topic accurately and practically
- **Deck title**: create a concise, human-readable title for the deck, normally 3-7 words. Prefer the topic and practical angle over copying the full request
- **Minimum information principle**: one idea per card. Prefer splitting long lists into separate cards over bundling them into one answer
- **Make every card self-contained**: include enough topic context in each question that the card can be reviewed on its own
- **Mix question types**: factual recall, conceptual understanding, application, diagnosis, and trade-offs
- **Write cards in {language}**
- **No trivial cards**: every card should test something genuinely worth remembering
- **No meta-cards**: never create cards about the request itself, your approach, or the generated deck structure
- **Disambiguate confusable concepts**: highlight the distinguishing feature when similar terms or processes appear
- **Build on fundamentals**: include prerequisite concepts in the question rather than assuming prior cards
- **Logical order**: arrange cards so foundational concepts come first — definitions before applications, causes before effects
- **Answers should be concise but complete** — typically 1-3 sentences
- **Lists in answers**: when an answer contains a numbered or bulleted list, use <br> between items for readability
- **Bold the gist of every answer**, with <b>...</b>, so a reader who recalled it correctly can confirm that at a glance instead of re-reading. Do it every time — a reader learns to look at the bold first, and an answer left bare sends them back to reading all of it. The one exception is an answer that is already its own gist: a term, a name, a number, or a phrase of a few words
- **Choose the span by a test, not by what looks important.** THE TEST: cut the bolded words out, and the answer should stop answering the question; read on their own, they should be enough for a reader who recalled the answer to confirm it. That is usually a phrase rather than a single noun — a few words, never most of the answer — and it is never a word the question already contains. Where an answer has parallel parts — a list, or the two sides of a contrast — put one span in each part, chosen by the same test, and mark every part or none
- **Bold belongs in the answer only**: never in a question and never in the "example" field

  Passes: "Each leader accepts writes locally <b>without waiting for the others</b>, then propagates its changes asynchronously."
  Fails:  "Each <b>leader</b> accepts writes locally without waiting for the others." (the question already said leader — the reader had to supply every word except that one)
- **No italics, ever**: do not use <em>, <i>, or any italic formatting
- **Example field**: make cards usable as standalone learning material, not just memory prompts. For every non-trivial concept, fill the "example" field with a concrete example, scenario, counterexample, common gotcha, misconception, vivid analogy, or practical application. If the request involves software engineering or programming, include code snippets where they clarify the idea and use <pre><code>...</code></pre> tags. Leave "example" as an empty string only for atomic facts where an example would add no value

Output ONLY a JSON object with "title" and "cards" fields. The "title" field is a concise deck title. The "cards" field is an array of objects with "question", "answer", and optionally "example" fields. No markdown, no explanation, no wrapper — just the raw JSON object.

Example format:
{{
  "title": "Cognitive Load for Engineers",
  "cards": [
    {{"question": "What is X?", "answer": "X is...", "example": ""}},
    {{"question": "How would you apply Y in practice?", "answer": "Use Y when...", "example": "For example, in a software team..."}}
  ]
}}

Generate the deck now as a JSON object:"""


VALID_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


_LANG_NAMES: dict[str, str] = {
    "en": "English", "ru": "Russian", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "no": "Norwegian", "nb": "Norwegian",
    "sv": "Swedish", "da": "Danish", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "ar": "Arabic", "he": "Hebrew", "uk": "Ukrainian",
    "cs": "Czech", "fi": "Finnish",
}


def build_vocab_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    level: str,
    native_language: str,
    is_article: bool = False,
    topic: str = "",
) -> str:
    """Build a prompt to extract vocabulary above the reader's level."""
    native_name = _LANG_NAMES.get(native_language, native_language)
    if is_article:
        source_header = f'Article: "{book_title}"'
        text_label = "Article text"
    else:
        source_header = f'Book: "{book_title}"\nChapter: "{chapter_title}"'
        text_label = "Chapter text"

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Extract vocabulary ONLY related to: {topic}. "
            "Skip words unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    return f"""You are an expert language teacher creating Anki vocabulary cards.

{source_header}
Reader's level: {level} (CEFR)
Reader's native language: {native_name}
Translate to: {native_name}

Extract words and phrases from the text that a {level}-level reader would NOT already know. \
These are words above {level} — uncommon, literary, domain-specific, or idiomatic expressions \
that a learner at this level would benefit from studying.{topic_instruction}

Guidelines:
- **Skip common words** that any {level} reader would know
- **Include**: uncommon single words, idiomatic phrases, phrasal verbs, collocations, literary/formal vocabulary
- **Context sentence**: use the EXACT sentence from the text where the word appears (or shorten it if too long, but keep the word in context). Wrap the target word/phrase in **&lt;b&gt;** tags to highlight it
- **Translation**: natural translation to {native_name}, not word-for-word
- **Definition**: brief explanation in the source language (1 sentence max)
- **Example**: one additional example sentence (NOT from the text) showing typical usage. Wrap the target word/phrase in **&lt;b&gt;** tags
- **Pronunciation**: IPA transcription (e.g. "/juːˈbɪkwɪtəs/") — skip for phrases and idioms
- **Etymology**: brief word origin in the source language, starting with a label in that language (e.g. "Origin: Latin ubique = everywhere" for English, "Herkunft: Latein ubique = überall" for German). Skip for common roots or phrases
- **Dictionary form**: ALWAYS use the base/dictionary form in the "word" field, even if the text has an inflected form. Verbs must be infinitive with "to" (e.g. text says "ensconced" → word is "to ensconce"; text says "crouching" → word is "to crouch"). Nouns must be singular. Adjectives must be positive degree
- **Correct spelling**: spell the word using standard, correct dictionary spelling. It must be the same word that appears highlighted in the context sentence (just its base form) — never invent, misspell, or guess a word that is not actually in the text
- **Grammar notes**: when useful, add brief grammar info in the "word" field that the READER can understand — e.g. gender for nouns (der/die/das, le/la). Use notation the reader knows based on their native language. Skip for English and Russian words
- **No proper nouns** (names of people, places, brands) unless they have a general meaning
- **No numbers, dates, or abbreviations**
- For phrases/idioms: the "word" field should contain the full phrase in base form
- **Usage**: decide whether the reader would ever use this word THEMSELVES, in speech or in their own writing — that decides which way the card is asked. "active": a word people actually use, formal ones included (e.g. "ubiquitous", "to come to grips with"); the card asks the reader to produce it from its meaning. "passive": a word the reader will only ever need to understand on the page — archaic or dated words, literary and poetic ones, rare words where speakers reach for an everyday synonym instead, narrow technical jargon; the card only asks what it means, since training the reader to produce it would train a skill they will never use, and a card asking for "susurrus" by its meaning marks them wrong for answering "whisper". The test is whether the reader would use it, not how rare it is. If unsure, choose "active"
- **Register**: a short label in the source language for a word whose register is marked — e.g. "literary", "archaic", "dated", "formal", "informal", "slang", "technical", "rare" for English; "gehoben", "veraltet", "umgangssprachlich" for German. Empty for neutral words. Every "passive" word needs one: it tells the reader why they are only learning to recognise it

Output ONLY a JSON array. No markdown, no explanation, no wrapper.

Example format:
[
  {{"word": "ubiquitous", "pronunciation": "/juːˈbɪkwɪtəs/", "context": "Smartphones have become <b>ubiquitous</b> in modern life.", "translation": "...", "definition": "Present or found everywhere", "example": "Coffee shops are <b>ubiquitous</b> in big cities.", "etymology": "Latin ubique = everywhere", "usage": "active", "register": ""}},
  {{"word": "to come to grips with", "pronunciation": "", "context": "She had to <b>come to grips with</b> the new reality.", "translation": "...", "definition": "To begin to understand and deal with something difficult", "example": "It took him months to <b>come to grips with</b> the loss.", "etymology": "", "usage": "active", "register": ""}},
  {{"word": "susurrus", "pronunciation": "/sjuːˈsʌrəs/", "context": "The <b>susurrus</b> of the leaves lulled her to sleep.", "translation": "...", "definition": "A soft whispering or rustling sound", "example": "the <b>susurrus</b> of distant traffic", "etymology": "Latin susurrus = whisper", "usage": "passive", "register": "literary"}}
]

{text_label}:
---
{chapter_text}
---

Extract vocabulary above {level} as a JSON array:"""


PRACTICE_DEPTH_INSTRUCTIONS = {
    0: (
        "Drill only the single most important building block this chapter teaches."
    ),
    1: (
        "Drill the core building blocks: the pieces a reader needs to assemble the "
        "chapter's main techniques. Skip minor utilities and trivial examples."
    ),
    2: (
        "Drill every building block the chapter teaches, including the variants it shows "
        "(timed, interruptible, failure handling) and notable edge cases, each on its own card."
    ),
}

# Plain strings, not f-strings, so the code's braces need no doubling.
_PRACTICE_EXAMPLES = r"""[
  {"question": "<b>Bounded buffer: put()</b><br>Block while the buffer is full, then add the item and wake a waiting consumer.<pre><code>// given\nLock lock;\nCondition notFull, notEmpty;\nQueue&lt;T&gt; items;\nint capacity;\n\nvoid put(T item) throws InterruptedException</code></pre>", "answer": "<pre><code>void put(T item) throws InterruptedException {\n    lock.lock();\n    try {\n        <b>while (items.size() == capacity) {</b>\n            <b>notFull.await();</b>\n        }\n        items.add(item);\n        <b>notEmpty.signal();</b>\n    } finally {\n        lock.unlock();\n    }\n}</code></pre>", "example": "Wait in a loop, not an if: await() can wake spuriously or after another producer filled the slot. Signal the other condition, and unlock in finally. take() is the mirror image: wait on notEmpty, signal notFull."},
  {"question": "<b>Run tasks concurrently, collect results in order</b><br>Start every task on the pool, then gather their results in the order of the input list.<pre><code>// given\nExecutorService pool;\n\nList&lt;Integer&gt; runAll(List&lt;Supplier&lt;Integer&gt;&gt; tasks)</code></pre>", "answer": "<pre><code>List&lt;Integer&gt; runAll(List&lt;Supplier&lt;Integer&gt;&gt; tasks) {\n    List&lt;CompletableFuture&lt;Integer&gt;&gt; futures = tasks.stream()\n            <b>.map(task -&gt; CompletableFuture.supplyAsync(task, pool))</b>\n            .toList();\n    <b>return futures.stream().map(CompletableFuture::join).toList();</b>\n}</code></pre>", "example": "Start them all before joining any. One stream that both starts and joins would run the tasks one at a time. join() rethrows a task's failure wrapped in a CompletionException."}
]"""


def build_practice_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    topic: str = "",
    code_lang: str = "",
) -> str:
    """Build a prompt for practice katas: small building blocks written from memory.

    Each card is one block a candidate assembles interview answers from, about
    fifteen lines, by the same minimum-information principle as any other card:
    a large solution can only be recognised, never recalled whole, and a card
    that fails on any one of its details fails on every review.
    """
    depth_instruction = PRACTICE_DEPTH_INSTRUCTIONS[depth]

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Generate exercises ONLY related to: {topic}. "
            "Skip everything unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    code_lang_instruction = ""
    if code_lang:
        code_lang_instruction = (
            f"\n\nIMPORTANT: ALL code in questions and answers MUST be in {code_lang}. "
            f"Even if the book uses a different language, translate all examples to {code_lang}."
        )

    return f"""You are an expert programming interview coach turning a programming book into \
Anki practice cards. Each card is a small kata: one building block the reader writes from \
memory, the kind of piece a strong candidate assembles an interview answer from without \
stopping to work it out.

Book: "{book_title}"
Chapter: "{chapter_title}"

{depth_instruction}{topic_instruction}{code_lang_instruction}

THE TEST for every card: is this a block worth having ready — would writing it from memory \
make an interview answer faster and more correct? A bounded buffer's put(), fanning tasks \
out and joining their results, a retry with backoff, a sliding-window rate check. Not a \
whole system, and not a single keyword or line: a kata combines at least two moving parts \
(a lock, a condition and the state they guard).

Memorisation rules, the same ones every good flashcard follows:
- **One building block per card.** Break a large pattern into its blocks: an LRU cache is \
"get() with move-to-front", "put() with eviction" and "making it thread-safe" — never one \
card implementing the whole cache. A variant is its own card: a timed offer() and an \
interruptible put() are two cards, not two requirements on one
- **Small enough to recall whole**: the answer is at most about 15 lines of code. If it \
needs more, it is two blocks — split it
- **The question fixes the frame**, so there is one natural answer to compare against: a \
short bold title, a one-line goal, then a <pre><code> block listing the fields or \
parameters the answer may use (under "// given") and the exact signature to implement. \
Where two cards are siblings (put() and take() of one buffer), the title says which
- **The answer is just the block**: the method or few lines, in <pre><code>. No main \
method, no demo, no imports, no class wrapper unless the class is the block, and no \
comments
- **Bold the lines that carry the idea** — usually one or two constructs — with \
<b>...</b> inside the code: the lines the reader grades themselves on. Never most of the \
answer, and nothing in the question
- **"example" states the key point in a line or two**: why the block has this shape, the \
common mistake, or how it mirrors its sibling card
- **Blocks before what is built from them**: order the cards so a block comes before any \
card that uses it
- **Generic names, not the book's story**: name a block for what it does, so it carries \
over to any problem — lockBoth(Lock a, Lock b), not impendingBow(Friend bower). Skip glue \
code that only wires the book's sample classes together (creating and starting them, a \
main method in all but name)

Code rules:
- **Modern, correct code**: write the block as it is written today (Java 21+: var, \
records, switch patterns; Python 3.10+: `X | None`, `list[int]`), with the right \
primitives (ConcurrentHashMap or a lock, not blanket synchronized) and correct handling of \
interruption and failure — minimal, but nothing a reviewer would flag
- **Chapters without code still have blocks**: a chapter on rate limiting gives "sliding \
window: tryAcquire()"; one on URL shortening gives "Base62-encode an id". Return [] only \
for chapters with no technical content at all (preface, acknowledgments)
- **All fields are HTML**: escape &lt; &gt; &amp; in code
- **No italics**

Output ONLY a JSON array of objects with "question", "answer" and "example". No markdown, \
no explanation, no wrapper.

{_PRACTICE_EXAMPLES}

Chapter text:
---
{chapter_text}
---

Generate the practice cards now as a JSON array:"""


IDIOMS_DEPTH_INSTRUCTIONS = {
    0: (
        "Drill only the single idiom this chapter is built around, if it has one worth "
        "writing from memory. Otherwise return []."
    ),
    1: (
        "Drill the core idioms this chapter teaches: the ones a reader would come away "
        "writing in real code."
    ),
    2: (
        "Drill every idiom this chapter teaches that passes the test below, including the "
        "variants it shows for timeouts, cancellation, failure and edge cases."
    ),
}

# Plain strings, not f-strings: the cloze braces would otherwise need doubling
# twice over.
_IDIOM_EXAMPLES = r"""[
  {"type": "snippet", "context": "Wait for a condition with an intrinsic lock", "question": "<pre><code>synchronized (lock) {\n    {{c1::while (!ready)}} {\n        lock.wait();\n    }\n    consume();\n}</code></pre>", "answer": "A loop, never an if: wait() can wake spuriously, or after another thread took the condition back.", "example": "The notifying side sets <code>ready = true</code> and calls <code>lock.notifyAll()</code> inside the same <code>synchronized (lock)</code> block."},
  {"type": "snippet", "context": "Shut an executor down, giving running tasks a deadline", "question": "<pre><code>pool.shutdown();\nif (!pool.{{c1::awaitTermination(30, TimeUnit.SECONDS)}}) {\n    {{c2::pool.shutdownNow();}}\n}</code></pre>", "answer": "shutdown() only stops new tasks; awaitTermination() bounds the wait, and shutdownNow() interrupts whatever is still running.", "example": "Since Java 19 an <code>ExecutorService</code> is <code>AutoCloseable</code>: <code>try (var pool = Executors.newFixedThreadPool(4)) { … }</code> shuts down and waits on close."},
  {"type": "line", "question": "Given <code>Map&lt;String, List&lt;Integer&gt;&gt; index</code>, append <code>n</code> to the list under <code>key</code>, creating the list if it's missing", "answer": "index.computeIfAbsent(key, k -> new ArrayList<>()).add(n);", "example": "One lookup instead of get / null check / put. On a <code>ConcurrentHashMap</code> the creation is atomic too."}
]"""


def build_idioms_prompt(
    book_title: str,
    chapter_title: str,
    chapter_text: str,
    depth: int,
    topic: str = "",
    code_lang: str = "",
) -> str:
    """Build a prompt for idiom drill cards: code the reader types from memory.

    For interview preparation, where the point is writing small idioms without
    pausing. Most worthwhile idioms span lines, and Anki's answer box takes
    one, so the main form is a snippet with its key piece hidden as a typed
    cloze; whole lines are the second form, where the question can fix every
    name the answer uses. Anki compares the typing character by character, so
    the rules are about leaving exactly one way to write the answer.
    """
    depth_instruction = IDIOMS_DEPTH_INSTRUCTIONS[depth]

    topic_instruction = ""
    if topic:
        topic_instruction = (
            f"\n\nIMPORTANT: Generate cards ONLY about: {topic}. "
            "Skip everything unrelated to this topic. "
            "If the text contains nothing relevant, return an empty JSON array []."
        )

    language = code_lang or "the book's language"
    code_lang_instruction = ""
    if code_lang:
        code_lang_instruction = (
            f"\n\nIMPORTANT: ALL code MUST be in {code_lang}. Even if the book uses a "
            f"different language, drill the {code_lang} way of doing the same thing."
        )

    return f"""You are an expert programming interview coach turning a programming book into \
Anki drill cards. The reader is preparing for coding interviews and wants the small idioms \
in their fingers: written without pausing to think, the way a strong candidate writes them \
at a whiteboard.

Book: "{book_title}"
Chapter: "{chapter_title}"

{depth_instruction}{topic_instruction}{code_lang_instruction}

THE TEST every idiom must pass: would an interviewer expect a strong candidate to write this \
from memory — or would a working engineer type it every week? Drill the shapes that are \
easy to get subtly wrong and that people reach for: lock() / try / finally unlock(), wait() \
inside a while loop, executor shutdown with a timeout, a CountDownLatch or CompletableFuture \
used correctly, a volatile flag, computeIfAbsent. Skip what fails it: syntax any developer \
knows (new Thread(r).start(), a getter), classes that exist only in the book's sample code, \
and APIs a reader would look up rather than remember.

**Modern {language}, whatever the book's age.** Write idioms as they are written today \
(for Java: 21+, with var, records, try-with-resources on an ExecutorService, virtual \
threads where they fit). Where the book teaches an older form, drill the modern one and \
name the old form in "example". Format code the standard way for the language (for Java, \
4-space indents and K&R braces), always the same way, so spacing never decides whether \
the typed answer matches.

Two kinds of card:

**"snippet" — the main kind.** A short snippet (2 to 10 lines) showing the idiom in \
context, with its key piece hidden as a cloze: {{{{c1::...}}}}. The reader sees the rest \
and types the hidden piece; Anki compares it character by character.
- The question is the snippet in <pre><code>...</code></pre>, HTML-escaped (&lt; &gt; &amp;). \
"context" is a short line naming what the snippet does, shown above it
- Hide the piece that matters — the part people get wrong or forget: the while in a wait \
loop, the unlock in finally, the timeout arguments, the volatile keyword. Never boilerplate
- Hide the smallest piece that carries the idiom: the keyword, call or condition it turns \
on. Hide synchronized, not the whole method signature around it; never make the reader \
type a name that only exists in the book's example
- Each hidden piece is on ONE line (the answer box takes one line) and contains no curly \
braces, which would break Anki's cloze syntax: leave a block's opening brace visible after \
the gap, as in {{{{c1::while (!ready)}}}} {{
- The visible code fixes every name the hidden piece uses, so there is one way to write it
- At most two hidden pieces per snippet, each with its own number (c1, c2), and only when \
both are worth drilling: each becomes its own card
- "answer" is one line on WHY the idiom has this shape — what goes wrong without it. \
Interviewers ask why, not just how
- "example" names the common mistake, the old or alternative form, or the other half of \
the idiom (the notifying side of a wait); empty if there is nothing to add

**"line" — a whole line to type.** Only where the question can fix every name and type \
the answer uses, by stating them: "Given <code>ExecutorService pool</code> and \
<code>Callable&lt;Integer&gt; task</code>, …". Where the line declares something, the \
question gives the declaration exactly as the answer writes it — "into \
<code>var pool</code>", "as a <code>private final Lock</code> field named \
<code>lock</code>" — so the reader never has to guess between var and a type, or whether \
the field is final.
- "answer" is the exact line: plain text, no HTML, no <code>, nothing else
- "example" gives the why and any equally valid forms, so a reader who typed a valid \
variant can see that it was valid

Guidelines:
- **One card per idiom**: never two cards drilling the same piece of the same idiom
- **No trivia**: every card must pass the test above. A chapter with no idioms worth \
drilling returns []
- **Bold nothing, and no italics**: the cloze highlighting is the emphasis

Output ONLY a JSON array of objects with "type" ("snippet" or "line"), "question", \
"answer", "example", and "context" for snippets. No markdown, no explanation, no wrapper.

{_IDIOM_EXAMPLES}

Chapter text:
---
{chapter_text}
---

Generate the drill cards now as a JSON array:"""
