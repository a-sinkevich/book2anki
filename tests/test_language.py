from book2anki.language import detect_language


def test_override():
    assert detect_language("any text", override="ru") == "ru"


def test_english_text():
    text = "This is a long enough English text to be detected properly by the language detector."
    assert detect_language(text) == "en"


def test_russian_text():
    text = "Это достаточно длинный русский текст для определения языка детектором."
    assert detect_language(text) == "ru"
