"""Index storage: SQLite for metadata + tags, a .npy matrix for audio vectors.

Row `row` of vectors.npy is the normalized vector for the track with that
`row` value in the `tracks` table. The whole index is held in memory at
query time (≈ 312 bytes/track for vectors), which keeps lookups well under
a second up to ~100k tracks.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config
from .features import DIMENSIONS
from .tagging import Tag
from .textutil import normalize_artist, normalize_text, song_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id     INTEGER PRIMARY KEY,
    row          INTEGER NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    album        TEXT NOT NULL DEFAULT '',
    genre        TEXT NOT NULL DEFAULT '',
    release_date TEXT NOT NULL DEFAULT '',
    year         INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    preview_url  TEXT NOT NULL,
    artwork_url  TEXT NOT NULL DEFAULT '',
    song_key     TEXT NOT NULL,
    bpm          REAL NOT NULL,
    energy       REAL NOT NULL,
    onset_rate   REAL NOT NULL,
    context      TEXT NOT NULL DEFAULT 'unknown',
    mood_tags    TEXT NOT NULL DEFAULT '[]',
    confidence   REAL NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'seed'  -- 'seed' (batch indexer) or 'on_demand'
);
CREATE INDEX IF NOT EXISTS tracks_song_key ON tracks(song_key);
"""

COLUMNS = (
    "track_id", "row", "title", "artist", "album", "genre", "release_date", "year", "duration_ms",
    "preview_url", "artwork_url", "song_key", "bpm", "energy", "onset_rate", "context", "mood_tags", "confidence",
    "source",
)


@dataclass
class IndexedTrack:
    track_id: int
    row: int
    title: str
    artist: str
    album: str
    genre: str
    release_date: str
    year: int
    duration_ms: int
    preview_url: str
    artwork_url: str
    song_key: str
    bpm: float
    energy: float
    onset_rate: float
    context: str = "unknown"
    mood_tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "seed"

    @property
    def tag(self) -> Tag:
        return Tag(self.context, self.mood_tags, self.confidence)

    @property
    def artist_key(self) -> str:
        return normalize_artist(self.artist)

    @property
    def genre_key(self) -> str:
        return normalize_text(self.genre)

    def to_api(self) -> dict:
        return {
            "track_id": self.track_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "genre": self.genre,
            "release_date": self.release_date,
            "year": self.year,
            "duration_ms": self.duration_ms,
            "preview_url": self.preview_url,
            "artwork_url": self.artwork_url,
            "bpm": round(self.bpm, 1),
            "context": self.context,
            "mood_tags": self.mood_tags,
            "tag_confidence": round(self.confidence, 2),
        }


def _row_to_track(row: sqlite3.Row) -> IndexedTrack:
    values = dict(row)
    values["mood_tags"] = json.loads(values["mood_tags"])
    return IndexedTrack(**values)


class Index:
    """In-memory view of the index with persistence for on-demand additions."""

    def __init__(self, db_path: Path = config.DB_PATH, matrix_path: Path = config.MATRIX_PATH) -> None:
        self.db_path = db_path
        self.matrix_path = matrix_path
        self.lock = threading.Lock()
        self.tracks: list[IndexedTrack] = []
        self.matrix = np.zeros((0, DIMENSIONS), dtype=np.float32)
        self._by_id: dict[int, int] = {}
        self._by_key: dict[str, int] = {}

    # MARK: Loading and writing

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        return connection

    @classmethod
    def load(cls, db_path: Path = config.DB_PATH, matrix_path: Path = config.MATRIX_PATH) -> "Index":
        index = cls(db_path, matrix_path)
        if not db_path.exists() or not matrix_path.exists():
            raise FileNotFoundError(f"No index at {db_path.parent}. Run `python -m similarity.index` first.")
        with index._connect() as connection:
            rows = connection.execute(f"SELECT {', '.join(COLUMNS)} FROM tracks ORDER BY row").fetchall()
        index.tracks = [_row_to_track(r) for r in rows]
        index.matrix = np.load(matrix_path).astype(np.float32)
        if index.matrix.shape != (len(index.tracks), DIMENSIONS):
            raise ValueError(f"vectors.npy shape {index.matrix.shape} doesn't match {len(index.tracks)} tracks")
        index._reindex()
        return index

    def _reindex(self) -> None:
        self._by_id = {t.track_id: i for i, t in enumerate(self.tracks)}
        self._by_key = {}
        for i, track in enumerate(self.tracks):
            self._by_key.setdefault(track.song_key, i)

    def write_all(self, tracks: list[IndexedTrack], matrix: np.ndarray) -> None:
        """Replaces the whole index (used by the batch indexer)."""
        assert matrix.shape == (len(tracks), DIMENSIONS)
        with self._connect() as connection:
            connection.execute("DELETE FROM tracks")
            connection.executemany(
                f"INSERT INTO tracks ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                [self._values(t) for t in tracks],
            )
        self._save_matrix(matrix)
        self.tracks = list(tracks)
        self.matrix = matrix.astype(np.float32)
        self._reindex()

    def add(self, track: IndexedTrack, vector: np.ndarray) -> IndexedTrack:
        """Appends one track (on-demand indexing) and persists it."""
        added = self.add_many([track], vector.reshape(1, DIMENSIONS))
        return added[0] if added else (self.by_id(track.track_id) or self.by_title_artist(track.title, track.artist))

    def add_many(self, tracks: list[IndexedTrack], vectors: np.ndarray) -> list[IndexedTrack]:
        """Appends tracks not already indexed (by trackId or song identity) and persists them."""
        with self.lock:
            keep: list[int] = []
            seen_ids, seen_keys = set(self._by_id), set(self._by_key)
            for i, track in enumerate(tracks):
                if track.track_id in seen_ids or track.song_key in seen_keys:
                    continue
                seen_ids.add(track.track_id)
                seen_keys.add(track.song_key)
                keep.append(i)
            if not keep:
                return []
            added = [tracks[i] for i in keep]
            for offset, track in enumerate(added):
                track.row = len(self.tracks) + offset
            matrix = np.vstack([self.matrix, vectors[keep].astype(np.float32)])
            with self._connect() as connection:
                connection.executemany(
                    f"INSERT INTO tracks ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                    [self._values(t) for t in added],
                )
            self._save_matrix(matrix)
            # Readers index rows by matrix position, so publish tracks before the matrix.
            self.tracks = self.tracks + added
            self.matrix = matrix
            self._reindex()
            return added

    def _save_matrix(self, matrix: np.ndarray) -> None:
        self.matrix_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.matrix_path.with_name(self.matrix_path.stem + ".tmp.npy")
        np.save(temporary, matrix.astype(np.float32))
        temporary.replace(self.matrix_path)

    @staticmethod
    def _values(track: IndexedTrack) -> tuple:
        return tuple(
            json.dumps(track.mood_tags, ensure_ascii=False) if column == "mood_tags" else getattr(track, column)
            for column in COLUMNS
        )

    # MARK: Lookup

    def __len__(self) -> int:
        return len(self.tracks)

    def by_id(self, track_id: int) -> IndexedTrack | None:
        row = self._by_id.get(track_id)
        return self.tracks[row] if row is not None else None

    def by_title_artist(self, title: str, artist: str) -> IndexedTrack | None:
        row = self._by_key.get(song_key(title, artist))
        return self.tracks[row] if row is not None else None
