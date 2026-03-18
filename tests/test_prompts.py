from book2anki.prompts import DEPTH_INSTRUCTIONS, build_prompt


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
    for depth in (1, 2, 3):
        prompt = build_prompt("Book", "Ch", "text", depth, "en")
        assert DEPTH_INSTRUCTIONS[depth][:20] in prompt


def test_build_prompt_language():
    prompt = build_prompt("Book", "Ch", "text", 1, "ru")
    assert "ru" in prompt
