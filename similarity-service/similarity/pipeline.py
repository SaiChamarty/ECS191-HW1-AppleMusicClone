"""Shared analysis pipeline: catalog tracks → previews → features → tags → index rows.

Used by the batch indexer, on-demand indexing, and background expansion.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from . import features, tagging
from .itunes import Track
from .previews import download_previews
from .store import Index, IndexedTrack

log = logging.getLogger(__name__)


def indexed_track(track: Track, raw: np.ndarray, tag: tagging.Tag, row: int = -1,
                  source: str = "seed") -> IndexedTrack:
    return IndexedTrack(
        track_id=track.track_id,
        row=row,
        title=track.title,
        artist=track.artist,
        album=track.album,
        genre=track.genre,
        release_date=track.release_date,
        year=track.year,
        duration_ms=track.duration_ms,
        preview_url=track.preview_url,
        artwork_url=track.artwork_url,
        song_key=track.key,
        bpm=float(raw[features.BPM_INDEX]),
        energy=float(raw[features.ENERGY_INDEX]),
        onset_rate=float(raw[features.ONSET_RATE_INDEX]),
        context=tag.context,
        mood_tags=tag.mood_tags,
        confidence=tag.confidence,
        source=source,
    )


def _extract(job: tuple[int, str]) -> tuple[int, np.ndarray | None, str | None]:
    track_id, path = job
    try:
        return track_id, features.extract_cached(track_id, Path(path)), None
    except Exception as error:  # noqa: BLE001 - reported and skipped
        return track_id, None, str(error)


def extract_all(audio: dict[int, Path], workers: int) -> dict[int, np.ndarray]:
    """Features for every downloaded preview; cached per track, extracted in parallel."""
    vectors: dict[int, np.ndarray] = {}
    pending: list[tuple[int, str]] = []
    for track_id, path in audio.items():
        cached = features.feature_path(track_id)
        if cached.exists():
            vectors[track_id] = np.load(cached)
        else:
            pending.append((track_id, str(path)))
    log.info("Features: %d cached, %d to extract", len(vectors), len(pending))
    if not pending:
        return vectors
    with ProcessPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
        futures = [pool.submit(_extract, job) for job in pending]
        for done, future in enumerate(as_completed(futures), start=1):
            track_id, vector, error = future.result()
            if vector is None:
                log.warning("Feature extraction failed for %s: %s", track_id, error)
            else:
                vectors[track_id] = vector
            if done % 25 == 0 or done == len(futures):
                log.info("Extracted %d/%d", done, len(futures))
    return vectors


def analyze(tracks: list[Track], workers: int = 4, discard_audio: bool = False) -> list[tuple[Track, np.ndarray]]:
    """Downloads previews and extracts features. Returns tracks that could be analyzed.

    Songs whose features are already cached are not downloaded again.
    """
    vectors: dict[int, np.ndarray] = {}
    needs_audio: list[Track] = []
    for track in tracks:
        cached = features.feature_path(track.track_id)
        if cached.exists() and (vector := np.load(cached)).shape == (features.DIMENSIONS,):
            vectors[track.track_id] = vector
        else:
            needs_audio.append(track)
    if vectors:
        log.info("Features already cached for %d tracks; downloading previews for %d", len(vectors), len(needs_audio))

    audio = asyncio.run(download_previews(needs_audio)) if needs_audio else {}
    vectors.update(extract_all(audio, workers))
    if discard_audio:
        # Features are cached, so the preview is no longer needed.
        for track_id in vectors:
            if (path := audio.get(track_id)) is not None:
                path.unlink(missing_ok=True)
    return [(t, vectors[t.track_id]) for t in tracks if t.track_id in vectors]


def tag_records(analyzed: list[tuple[Track, np.ndarray]], records: list[IndexedTrack], skip_tagging: bool = False) -> None:
    """Fills context/mood tags in place (cached tags only when skipping Claude)."""
    if skip_tagging:
        tags = {r.track_id: tagging.load_cached_tag(r.track_id) or tagging.Tag() for r in records}
    else:
        tags = tagging.tag_tracks([
            {**t.to_dict(), "bpm": r.bpm, "energy": r.energy, "onset_rate": r.onset_rate}
            for (t, _), r in zip(analyzed, records)
        ])
    for record in records:
        tag = tags[record.track_id]
        record.context, record.mood_tags, record.confidence = tag.context, tag.mood_tags, tag.confidence


def add_to_index(index: Index, stats: dict, tracks: list[Track], source: str, workers: int = 4,
                 discard_audio: bool = False) -> list[IndexedTrack]:
    """Analyzes new tracks and appends them using the saved normalization stats."""
    fresh = [t for t in tracks if index.by_id(t.track_id) is None and index.by_title_artist(t.title, t.artist) is None]
    if not fresh:
        return []
    analyzed = analyze(fresh, workers, discard_audio)
    if not analyzed:
        return []
    records = [indexed_track(t, raw, tagging.Tag(), source=source) for t, raw in analyzed]
    tag_records(analyzed, records)
    vectors = features.transform(np.vstack([raw for _, raw in analyzed]), stats)
    return index.add_many(records, vectors)
