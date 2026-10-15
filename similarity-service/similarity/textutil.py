"""Script-agnostic text normalization and defensive JSON extraction."""

from __future__ import annotations

import json
import re
import unicodedata

# Version markers that make two recordings "the same song" for dedupe.
_VERSION_SUFFIX = re.compile(
    r"\s+[-–—]\s+(?:\d{4}\s+)?(?:remaster(?:ed)?|live|mono|stereo|single|radio|edit|version|mix|remix|"
    r"acoustic|demo|deluxe|bonus|from\b|feat\b|ft\b|with\b).*$",
    re.IGNORECASE,
)
_BRACKETED = re.compile(r"[\(\[\{（【].*?[\)\]\}）】]")
_FEATURING = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+.*$", re.IGNORECASE)


def _strip_punctuation(text: str) -> str:
    """Removes punctuation/symbols in any script; keeps letters, marks and digits."""
    kept = [
        ch if not unicodedata.category(ch).startswith(("P", "S")) else " "
        for ch in text
    ]
    return " ".join("".join(kept).split())


def normalize_text(text: str) -> str:
    """Casefolded, NFKC-normalized, punctuation-free text. Works for any script."""
    return _strip_punctuation(unicodedata.normalize("NFKC", text).casefold())


def normalize_title(title: str) -> str:
    """Title with version markers removed: "Heroes (2017 Remaster)" → "heroes"."""
    text = unicodedata.normalize("NFKC", title)
    text = _VERSION_SUFFIX.sub("", text)
    stripped = _BRACKETED.sub(" ", text)
    # Titles that are entirely bracketed (rare) keep their content.
    text = stripped if stripped.strip() else text
    return normalize_text(text)


def normalize_artist(artist: str) -> str:
    """Primary artist with featured artists removed."""
    text = unicodedata.normalize("NFKC", artist)
    text = _BRACKETED.sub(" ", text)
    text = _FEATURING.sub("", text)
    return normalize_text(text)


def song_key(title: str, artist: str) -> str:
    """Identity of a song across releases (remasters, live cuts, edits)."""
    return f"{normalize_title(title)}|{normalize_artist(artist)}"


def first_json_array(text: str) -> str | None:
    """Returns the first balanced `[...]` in `text`, ignoring brackets inside strings."""
    start = text.find("[")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
        # Not valid JSON from this bracket; try the next one.
        start = text.find("[", start + 1)
    return None
