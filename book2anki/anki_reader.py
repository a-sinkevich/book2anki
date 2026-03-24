"""Read existing vocabulary words from the user's Anki collection."""

import html
import os
import platform
import shutil
import sqlite3
import tempfile


def _find_anki_collection() -> str | None:
    """Find the Anki collection.anki2 file for the default profile."""
    system = platform.system()
    if system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/Anki2")
    elif system == "Linux":
        base = os.path.expanduser("~/.local/share/Anki2")
    elif system == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "Anki2")
    else:
        return None

    if not os.path.isdir(base):
        return None

    # Try common profile names
    for profile in ("User 1", "user1", "Default"):
        path = os.path.join(base, profile, "collection.anki2")
        if os.path.isfile(path):
            return path

    # Fall back to first directory that contains collection.anki2
    try:
        for entry in sorted(os.listdir(base)):
            path = os.path.join(base, entry, "collection.anki2")
            if os.path.isfile(path):
                return path
    except OSError:
        pass

    return None


def read_vocab_words(tag_prefix: str = "vocab::") -> set[str]:
    """Read existing vocabulary words from the Anki collection.

    Finds the Anki DB, copies it to a temp file (to avoid lock issues),
    reads words from notes tagged with the given prefix, and returns
    a set of lowercase words for dedup matching.
    """
    collection_path = _find_anki_collection()
    if not collection_path:
        return set()

    try:
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "collection.anki2")
        shutil.copy2(collection_path, tmp_path)
        # Copy WAL and SHM files so recent changes (deletions) are included
        for suffix in ("-wal", "-shm"):
            wal_src = collection_path + suffix
            if os.path.isfile(wal_src):
                shutil.copy2(wal_src, tmp_path + suffix)
    except OSError:
        return set()

    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute(
            "SELECT flds FROM notes WHERE tags LIKE ?",
            (f"% {tag_prefix}%",),
        ).fetchall()
        # Also match when tag is at the start (no leading space)
        rows += conn.execute(
            "SELECT flds FROM notes WHERE tags LIKE ?",
            (f"{tag_prefix}%",),
        ).fetchall()
        conn.close()
    except (sqlite3.Error, OSError):
        return set()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    words: set[str] = set()
    for (flds,) in rows:
        # First field is the word (may contain HTML entities)
        word = html.unescape(flds.split("\x1f", 1)[0].strip())
        if word:
            words.add(word.lower())

    return words
