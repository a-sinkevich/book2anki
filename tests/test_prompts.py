from book2anki.prompts import DEPTH_INSTRUCTIONS, build_prompt, build_prompt_request


def test_build_prompt_contains_book_title():
    prompt = build_prompt("My Book", "Chapter 1", "Some text", 1, "en")
    assert "My Book" in prompt
    assert "Chapter 1" in prompt


def test_build_prompt_contains_chapter_text():
    prompt = build_prompt("Book", "Ch", "The actual content here", 1, "en")
    assert "The actual content here" in prompt


def test_build_prompt_contains_depth_instruction():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "core ideas" in prompt


def test_build_prompt_all_depths():
    for depth in (0, 1, 2, 3):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert DEPTH_INSTRUCTIONS[depth][:20] in prompt


def test_build_prompt_language():
    prompt = build_prompt("Book", "Ch", "text", 1, "ru")
    assert "ru" in prompt


def test_depth_zero_does_not_force_fixed_card_count():
    prompt = build_prompt("Book", "Ch", "text", 0, "en")
    assert "Do not aim for a fixed number of cards" in prompt
    assert "as many or as few as the content warrants" in prompt
    assert "2-3 cards" not in prompt


def test_build_prompt_pushes_examples_as_standalone_learning_material():
    prompt = build_prompt("Book", "Ch", "text", 1, "en")
    assert "standalone learning material" in prompt
    assert "For every non-trivial concept" in prompt
    assert "broader knowledge" in prompt
    assert "empty string only for atomic facts" in prompt


def test_programming_prompt_pushes_code_examples():
    prompt = build_prompt("Book", "Ch", "text", 1, "en", is_programming=True)
    assert "For every non-trivial programming concept" in prompt
    assert "minimal code snippet" in prompt
    assert "<pre><code>...</code></pre>" in prompt


def test_build_prompt_request_uses_study_request_without_source():
    prompt = build_prompt_request("Cognitive load theory for software engineers", 1, "en")
    assert "Study request" in prompt
    assert "Cognitive load theory for software engineers" in prompt
    assert "Use your broader knowledge" in prompt
    assert "standalone learning material" in prompt
    assert "concise deck title" in prompt
    assert '"title" and "cards" fields' in prompt
