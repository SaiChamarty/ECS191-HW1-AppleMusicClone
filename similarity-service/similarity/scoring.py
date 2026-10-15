"""Candidate generation (cosine over the full matrix) and weighted re-scoring."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from . import config
from .store import Index, IndexedTrack
from .tagging import Tag


@dataclass
class Breakdown:
    """Component scores in [0, 1] and their weighted total."""

    audio: float
    tags: float
    metadata: float
    tempo: float
    total: float

    def to_dict(self) -> dict:
        return {key: round(value, 4) for key, value in asdict(self).items()}


@dataclass
class Scored:
    track: IndexedTrack
    breakdown: Breakdown
    cosine: float


def tempo_closeness(bpm_a: float, bpm_b: float, sigma: float | None = None) -> float:
    """exp(-(d/sigma)^2) on log2 BPM distance, folded so half/double time are close."""
    sigma = sigma or float(config.SETTINGS["tempo_match"]["sigma_octaves"])
    if bpm_a <= 0 or bpm_b <= 0:
        return 0.0
    distance = abs(math.log2(bpm_a) - math.log2(bpm_b))
    folded = min(distance, abs(distance - 1.0))
    return math.exp(-((folded / sigma) ** 2))


def tag_match(query: Tag, candidate: Tag, weights: dict | None = None) -> float:
    """Context agreement (weighted higher) + mood-tag Jaccard, scaled by confidence."""
    weights = weights or config.SETTINGS["tag_match"]
    w_context, w_mood = float(weights["context"]), float(weights["mood"])
    confidence = math.sqrt(max(query.confidence, 0.0) * max(candidate.confidence, 0.0))
    if confidence == 0:
        return 0.0
    context = 1.0 if query.context == candidate.context and query.context != "unknown" else 0.0
    moods_q, moods_c = set(query.mood_tags), set(candidate.mood_tags)
    mood = len(moods_q & moods_c) / len(moods_q | moods_c) if moods_q and moods_c else 0.0
    return confidence * (w_context * context + w_mood * mood) / (w_context + w_mood)


def metadata_match(query: IndexedTrack, candidate: IndexedTrack, weights: dict | None = None) -> float:
    weights = weights or config.SETTINGS["metadata_match"]
    window = int(weights["year_window"])
    artist = 1.0 if query.artist_key and query.artist_key == candidate.artist_key else 0.0
    genre = 1.0 if query.genre_key and query.genre_key == candidate.genre_key else 0.0
    year = 1.0 if query.year and candidate.year and abs(query.year - candidate.year) <= window else 0.0
    total = float(weights["artist"]) + float(weights["genre"]) + float(weights["year"])
    return (float(weights["artist"]) * artist + float(weights["genre"]) * genre + float(weights["year"]) * year) / total


def score_pair(query: IndexedTrack, candidate: IndexedTrack, cosine: float, weights: dict | None = None) -> Breakdown:
    weights = weights or config.SETTINGS["score"]
    # Negative cosine means "opposite"; treat it as no audio similarity.
    audio = max(min(cosine, 1.0), 0.0)
    tags = tag_match(query.tag, candidate.tag)
    metadata = metadata_match(query, candidate)
    tempo = tempo_closeness(query.bpm, candidate.bpm)
    total = (
        float(weights["audio"]) * audio
        + float(weights["tags"]) * tags
        + float(weights["metadata"]) * metadata
        + float(weights["tempo"]) * tempo
    )
    return Breakdown(audio=audio, tags=tags, metadata=metadata, tempo=tempo, total=total)


def rank(
    index: Index,
    query: IndexedTrack,
    query_vector: np.ndarray,
    limit: int | None = None,
    candidates: int | None = None,
) -> list[Scored]:
    """Top `candidates` by cosine → weighted score → top `limit`, excluding the
    query song and duplicate versions (same normalized title + artist)."""
    settings = config.SETTINGS["score"]
    limit = limit or int(settings["results"])
    candidates = candidates or int(settings["candidates"])
    if len(index) == 0:
        return []

    sims = index.matrix @ query_vector.astype(np.float32)
    # Over-fetch slightly so excluded duplicates don't shrink the pool.
    pool = min(len(sims), candidates + 1)
    top = np.argpartition(-sims, pool - 1)[:pool] if pool < len(sims) else np.arange(len(sims))

    scored: list[Scored] = []
    for row in top:
        candidate = index.tracks[int(row)]
        if candidate.track_id == query.track_id or candidate.song_key == query.song_key:
            continue
        scored.append(Scored(candidate, score_pair(query, candidate, float(sims[row])), float(sims[row])))
    scored.sort(key=lambda s: s.breakdown.total, reverse=True)

    seen: set[str] = set()
    results: list[Scored] = []
    for item in scored:
        if item.track.song_key in seen:
            continue
        seen.add(item.track.song_key)
        results.append(item)
        if len(results) == limit:
            break
    return results
