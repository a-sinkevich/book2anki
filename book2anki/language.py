from langdetect import detect


def detect_language(text: str, override: str | None = None) -> str:
    """Detect the language of the text, or use the override if provided.

    Returns a language code like 'en' or 'ru'.
    """
    if override:
        return override

    sample = text[:5000]
    try:
        lang: str = detect(sample)
    except Exception:
        lang = "en"  # default fallback

    return lang
