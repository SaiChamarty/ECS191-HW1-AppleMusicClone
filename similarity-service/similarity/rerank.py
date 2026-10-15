"""Optional explain mode: one Claude call refines the top candidates and gives reasons.

Only used when a request sets explain=true. The default query path makes no
API calls.
"""

from __future__ import annotations

import json
import logging

from . import config
from .scoring import Scored
from .store import IndexedTrack
from .textutil import first_json_array

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You refine song recommendations for a music-similarity app that covers every genre, language and region.

You receive a query song and candidate songs. Each has metadata, context/mood tags (with a confidence), audio measurements, and pre-computed similarity scores in [0, 1] (audio, tags, metadata, tempo, total).

Pick the 10 candidates most similar to the query, best first, and give a one-line reason for each.

Rules:
- Use ONLY the data provided. Do not bring in outside facts about artists or songs.
- Reasons are one short line (under 20 words) and cite the provided evidence, e.g. tempo, energy, shared tags, audio score.
- Only use trackIds from the candidate list.
- Reply with ONLY a JSON array: [{"trackId": <int>, "reason": <string>}, ...]. No prose, no code fences."""


def _describe(track: IndexedTrack) -> dict:
    return {
        "trackId": track.track_id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "genre": track.genre,
        "year": track.year or None,
        "bpm": round(track.bpm, 1),
        "energy": round(track.energy, 4),
        "onset_rate": round(track.onset_rate, 2),
        "context": track.context,
        "mood_tags": track.mood_tags,
        "tag_confidence": round(track.confidence, 2),
    }


def build_payload(query: IndexedTrack, candidates: list[Scored]) -> dict:
    return {
        "query": _describe(query),
        "candidates": [{**_describe(c.track), "scores": c.breakdown.to_dict()} for c in candidates],
    }


def parse_rerank(text: str, candidate_ids: list[int], limit: int = 10) -> list[tuple[int, str]]:
    """Returns [(trackId, reason)], dropping unknown/duplicate ids. Raises ValueError if unusable."""
    raw = first_json_array(text)
    if raw is None:
        raise ValueError("no JSON array in response")
    allowed = set(candidate_ids)
    picked: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in json.loads(raw):
        if not isinstance(item, dict):
            continue
        try:
            track_id = int(item.get("trackId"))
        except (TypeError, ValueError):
            continue
        if track_id not in allowed or track_id in seen:
            continue
        seen.add(track_id)
        reason = " ".join(str(item.get("reason") or "").split())[:200]
        picked.append((track_id, reason))
        if len(picked) == limit:
            break
    if not picked:
        raise ValueError("no valid candidates in response")
    return picked


def rerank(query: IndexedTrack, candidates: list[Scored], limit: int = 10, client=None,
           model: str = config.RERANK_MODEL) -> list[tuple[Scored, str | None]]:
    """Refined top `limit` with reasons; tracks Claude omitted are filled from the default order."""
    if client is None:
        if not config.has_anthropic_key():
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        import anthropic

        client = anthropic.Anthropic()
    payload = build_payload(query, candidates)
    by_id = {c.track.track_id: c for c in candidates}
    response = client.messages.create(
        model=model,
        max_tokens=int(config.SETTINGS["rerank"]["max_tokens"]),
        system=SYSTEM_PROMPT,
        # Low effort: this is a short, constrained ranking task on a latency path.
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason == "refusal":
        raise ValueError("rerank request was declined")
    text = "".join(block.text for block in response.content if block.type == "text")
    picked = parse_rerank(text, list(by_id), limit)

    results: list[tuple[Scored, str | None]] = [(by_id[track_id], reason or None) for track_id, reason in picked]
    chosen = {track_id for track_id, _ in picked}
    for candidate in candidates:
        if len(results) == limit:
            break
        if candidate.track.track_id not in chosen:
            results.append((candidate, None))
    return results
