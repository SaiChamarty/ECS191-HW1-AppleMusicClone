"""Paths, environment variables, and tunables loaded from settings.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent

SETTINGS: dict = tomllib.loads(Path(__file__).with_name("settings.toml").read_text(encoding="utf-8"))

# Everything under cache/ and data/ is git-ignored. Audio lives only in cache/previews.
CACHE_DIR = Path(os.environ.get("SIMILARITY_CACHE_DIR", SERVICE_ROOT / "cache"))
DATA_DIR = Path(os.environ.get("SIMILARITY_DATA_DIR", SERVICE_ROOT / "data"))

ITUNES_CACHE_DIR = CACHE_DIR / "itunes"
PREVIEW_DIR = CACHE_DIR / "previews"
FEATURE_DIR = CACHE_DIR / "features"
TAG_DIR = CACHE_DIR / "tags"

DB_PATH = DATA_DIR / "index.sqlite"
MATRIX_PATH = DATA_DIR / "vectors.npy"
NORM_STATS_PATH = DATA_DIR / "norm_stats.json"

# Model IDs are overridable; defaults are the current Haiku / Sonnet models.
TAGGING_MODEL = os.environ.get("TAGGING_MODEL", "claude-haiku-4-5")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "claude-sonnet-5")

CONTEXTS: list[str] = list(SETTINGS["taxonomy"]["contexts"])
MAX_MOOD_TAGS: int = int(SETTINGS["taxonomy"]["max_mood_tags"])


def has_anthropic_key() -> bool:
    """True when ANTHROPIC_API_KEY is set (never read from files or code)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
