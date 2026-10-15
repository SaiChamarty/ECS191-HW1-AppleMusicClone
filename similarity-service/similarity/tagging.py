"""Context/mood tagging with the Claude API — metadata only, never lyrics or audio.

Tracks are sent in batches (20 by default); each result is cached per track so
reruns only tag new tracks. Without ANTHROPIC_API_KEY tagging is skipped and
tracks keep context "unknown" with confidence 0, which zeroes the tag component.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .textutil import first_json_array

log = logging.getLogger(__name__)


@dataclass
class Tag:
    context: str = "unknown"
    mood_tags: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class TagParseError(ValueError):
    pass


def system_prompt(contexts: list[str] = config.CONTEXTS, max_moods: int = config.MAX_MOOD_TAGS) -> str:
    return f"""You label songs with a listening context for a music-similarity index that covers every genre, language and region.

You receive a JSON array of tracks. Each has metadata only: trackId, title, artist, album, genre, year, and three audio measurements (bpm, energy = RMS loudness 0-1, onset_rate = note onsets per second).

Reply with ONLY a JSON array containing one object per input track, with exactly these keys:
{{"trackId": <the input trackId>, "context": <one of {json.dumps(contexts)}>, "mood_tags": [<up to {max_moods} short lowercase strings>], "confidence": <number from 0 to 1>}}

Rules:
- If you don't actually know the song, use "unknown" with confidence 0.3 or lower.
- Don't guess from the title alone. The audio measurements can support what you know about a song but are not enough on their own.
- Judge each song on its own terms; don't assume Western pop conventions for music from other traditions.
- JSON only: no prose, no markdown, no code fences."""


def build_payload(tracks: list[dict]) -> list[dict]:
    """Metadata sent to Claude. Deliberately excludes lyrics and audio."""
    return [
        {
            "trackId": t["track_id"],
            "title": t["title"],
            "artist": t["artist"],
            "album": t.get("album", ""),
            "genre": t.get("genre", ""),
            "year": t.get("year") or None,
            "bpm": round(float(t["bpm"]), 1) if t.get("bpm") is not None else None,
            "energy": round(float(t["energy"]), 4) if t.get("energy") is not None else None,
            "onset_rate": round(float(t["onset_rate"]), 2) if t.get("onset_rate") is not None else None,
        }
        for t in tracks
    ]


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    return min(max(number, 0.0), 1.0)


def parse_tags(
    text: str,
    expected_ids: set[int],
    contexts: list[str] = config.CONTEXTS,
    max_moods: int = config.MAX_MOOD_TAGS,
) -> dict[int, Tag]:
    """Parses Claude's reply defensively. Raises TagParseError if no JSON array is found.

    Unknown trackIds are dropped; off-taxonomy contexts become "unknown";
    confidence is clamped to [0, 1]; mood tags are trimmed and capped.
    """
    raw = first_json_array(text)
    if raw is None:
        raise TagParseError("no JSON array in response")
    items = json.loads(raw)
    allowed = set(contexts)
    tags: dict[int, Tag] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            track_id = int(item.get("trackId"))
        except (TypeError, ValueError):
            continue
        if track_id not in expected_ids:
            continue
        context = str(item.get("context", "unknown")).strip().lower()
        confidence = _coerce_confidence(item.get("confidence"))
        if context not in allowed:
            context = "unknown"
        if context == "unknown":
            confidence = min(confidence, 0.3)
        moods_value = item.get("mood_tags")
        moods = moods_value if isinstance(moods_value, list) else []
        cleaned: list[str] = []
        for mood in moods:
            if isinstance(mood, str) and (mood := " ".join(mood.lower().split())[:32]) and mood not in cleaned:
                cleaned.append(mood)
        tags[track_id] = Tag(context=context, mood_tags=cleaned[:max_moods], confidence=confidence)
    return tags


def _tag_path(track_id: int, tag_dir: Path) -> Path:
    return tag_dir / f"{track_id}.json"


def load_cached_tag(track_id: int, tag_dir: Path = config.TAG_DIR) -> Tag | None:
    path = _tag_path(track_id, tag_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Tag(context=data["context"], mood_tags=list(data["mood_tags"]), confidence=float(data["confidence"]))


def _make_client():
    import anthropic

    # Reads ANTHROPIC_API_KEY from the environment.
    return anthropic.Anthropic()


def _request(client, model: str, payload: list[dict], max_tokens: int) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt(),
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason == "refusal":
        raise TagParseError("request was declined")
    return "".join(block.text for block in response.content if block.type == "text")


def tag_tracks(
    tracks: list[dict],
    client=None,
    model: str = config.TAGGING_MODEL,
    batch_size: int | None = None,
    tag_dir: Path = config.TAG_DIR,
) -> dict[int, Tag]:
    """Returns tags for every track (cached or new). Untaggable tracks get Tag()."""
    batch_size = batch_size or int(config.SETTINGS["tagging"]["batch_size"])
    max_tokens = int(config.SETTINGS["tagging"]["max_tokens"])
    results: dict[int, Tag] = {}
    todo: list[dict] = []
    for track in tracks:
        cached = load_cached_tag(track["track_id"], tag_dir)
        if cached:
            results[track["track_id"]] = cached
        else:
            todo.append(track)

    if todo and client is None:
        if not config.has_anthropic_key():
            log.warning("ANTHROPIC_API_KEY not set; %d tracks left untagged (context=unknown)", len(todo))
            todo = []
        else:
            client = _make_client()

    tag_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(todo), batch_size):
        batch = todo[start : start + batch_size]
        expected = {t["track_id"] for t in batch}
        parsed: dict[int, Tag] = {}
        # One retry on any failure (API error, bad JSON, or missing tracks).
        for attempt in range(2):
            missing = [t for t in batch if t["track_id"] not in parsed]
            if not missing:
                break
            try:
                text = _request(client, model, build_payload(missing), max_tokens)
                parsed.update(parse_tags(text, {t["track_id"] for t in missing}))
            except Exception as error:  # noqa: BLE001 - tagging must never stop indexing
                log.warning("Tagging batch failed (attempt %d): %s", attempt + 1, error)
        for track_id, tag in parsed.items():
            _tag_path(track_id, tag_dir).write_text(json.dumps({**tag.to_dict(), "model": model}), encoding="utf-8")
        results.update(parsed)
        log.info("Tagged %d/%d tracks in batch", len(parsed), len(expected))

    # Not cached, so a later run retries them.
    for track in tracks:
        results.setdefault(track["track_id"], Tag())
    return results
