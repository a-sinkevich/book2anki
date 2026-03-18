"""Load API keys from a .env file without requiring python-dotenv."""

import os
from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple .env file (KEY=VALUE lines, # comments, optional quotes)."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return result

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def load_env() -> None:
    """Load variables from .env files into os.environ (won't overwrite existing vars).

    Search order:
      1. .env in the current working directory
      2. ~/.book2anki.env (cross-platform home directory)
    """
    candidates = [
        Path.cwd() / ".env",
        Path.home() / ".book2anki.env",
    ]
    for path in candidates:
        if path.is_file():
            for key, value in _parse_env_file(path).items():
                if key not in os.environ:
                    os.environ[key] = value
