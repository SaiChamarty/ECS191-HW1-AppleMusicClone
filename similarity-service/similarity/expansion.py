"""Background index growth around what users ask for.

Each query enqueues one job (per song and storefront). The worker gathers
candidates the index is likely missing — the query artist's other songs, the
top chart for the song's genre in the user's storefront, and more songs filed
under that genre — then analyzes and adds them. Clients re-query while the
response says `expanding: true` and get rankings over the larger index.

Nothing here assumes a musical tradition: candidates come from the user's own
storefront and the song's own catalog genre.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from . import config
from .itunes import ITunesClient, Track
from .pipeline import add_to_index
from .store import Index, IndexedTrack

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    track_id: int
    country: str


class Expander:
    def __init__(self, index: Index, stats: dict, itunes: ITunesClient, settings: dict | None = None) -> None:
        self.index = index
        self.stats = stats
        self.itunes = itunes
        self.settings = settings or config.SETTINGS["expansion"]
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        self._pending: set[Job] = set()
        self._done: set[Job] = set()
        # Sources already pulled, so popular artists/genres aren't fetched repeatedly.
        self._sources_done: set[str] = set()
        self._genre_ids: dict[str, int] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="index-expander", daemon=True)
            self._thread.start()

    def request(self, query: IndexedTrack, country: str) -> bool:
        """Queues expansion around `query`; True while that expansion is pending or running."""
        job = Job(query.track_id, country)
        with self._lock:
            if job in self._done:
                return False
            if job not in self._pending:
                if len(self._pending) >= int(self.settings["max_queue"]):
                    return False
                self._pending.add(job)
                self._queue.put(job)
            return True

    def is_expanding(self, track_id: int, country: str) -> bool:
        with self._lock:
            return Job(track_id, country) in self._pending

    # MARK: Worker

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                added = self.expand(job)
                log.info("Expansion for %s/%s added %d tracks (index: %d)", job.track_id, job.country,
                         len(added), len(self.index))
            except Exception:  # noqa: BLE001 - one failed job must not stop the worker
                log.exception("Expansion for %s/%s failed", job.track_id, job.country)
            finally:
                with self._lock:
                    self._pending.discard(job)
                    self._done.add(job)

    def expand(self, job: Job) -> list[IndexedTrack]:
        candidates = self.candidates(job)
        limit = int(self.settings["max_new_tracks"])
        fresh: list[Track] = []
        seen: set[str] = set()
        for track in candidates:
            if track.key in seen or self.index.by_id(track.track_id) or self.index.by_title_artist(track.title, track.artist):
                continue
            seen.add(track.key)
            fresh.append(track)
            if len(fresh) == limit:
                break
        if not fresh:
            return []
        return add_to_index(
            self.index, self.stats, fresh, source="expansion",
            workers=int(self.settings["workers"]), discard_audio=not bool(self.settings["keep_previews"]),
        )

    def candidates(self, job: Job) -> list[Track]:
        """Same artist first, then the genre chart and genre catalog in the user's storefront."""
        raw = self.itunes.lookup_raw(job.track_id, job.country) or self.itunes.lookup_raw(job.track_id)
        if raw is None:
            return []
        country = job.country
        artist_id = raw.get("artistId")
        genre = str(raw.get("primaryGenreName") or "")
        found: list[Track] = []

        def pull(source: str, fetch) -> bool:
            """Adds a source's tracks once; returns True if it produced any."""
            if source in self._sources_done:
                return True
            try:
                tracks = fetch()
            except Exception as error:  # noqa: BLE001 - a missing source just means fewer candidates
                log.warning("Candidate source %s failed: %s", source, error)
                return False
            self._sources_done.add(source)
            found.extend(tracks)
            return bool(tracks)

        if artist_id:
            pull(f"artist:{artist_id}:{country}",
                 lambda: self.itunes.artist_songs(int(artist_id), country, int(self.settings["artist_songs"])))
        genre_id = self._genre_id(genre)
        # Some storefronts have no charts or genre listings (e.g. Korea's iTunes
        # Store sells no music); fall back to the default storefront for those.
        for storefront in dict.fromkeys([country, self.itunes.country]):
            pulled_chart = pull(f"chart:{genre_id or 'all'}:{storefront}", lambda s=storefront: self.itunes.lookup_many(
                self.itunes.chart_ids(s, genre_id, int(self.settings["chart_size"])), s))
            pulled_genre = pull(f"genre:{genre.casefold()}:{storefront}",
                                lambda s=storefront: self.itunes.genre_songs(genre, s, int(self.settings["genre_songs"])))
            if pulled_chart or pulled_genre:
                break
        return found

    def _genre_id(self, genre: str) -> int | None:
        if not genre:
            return None
        if self._genre_ids is None:
            try:
                self._genre_ids = self.itunes.music_genre_ids()
            except Exception as error:  # noqa: BLE001 - fall back to the all-genre chart
                log.warning("Genre list unavailable: %s", error)
                self._genre_ids = {}
        return self._genre_ids.get(genre.casefold())
