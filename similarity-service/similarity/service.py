"""Online query path: resolve the song, index it on demand if needed, rank."""

from __future__ import annotations

import logging
import time

from . import config, features, tagging
from .expansion import Expander
from .itunes import ITunesClient
from .pipeline import indexed_track
from .previews import download_preview
from .rerank import rerank
from .scoring import Scored, rank
from .store import Index, IndexedTrack

log = logging.getLogger(__name__)


class SongNotFound(LookupError):
    pass


class SimilarityService:
    def __init__(self, index: Index, stats: dict, itunes: ITunesClient | None = None,
                 expander: Expander | None = None) -> None:
        self.index = index
        self.stats = stats
        self.itunes = itunes or ITunesClient()
        # Only the API server grows the index in the background; CLI tools don't.
        self.expander = expander

    @classmethod
    def load(cls, expand: bool = False) -> "SimilarityService":
        index, stats, itunes = Index.load(), features.load_stats(), ITunesClient()
        expander = None
        if expand and config.SETTINGS["expansion"]["enabled"]:
            expander = Expander(index, stats, itunes)
            expander.start()
        return cls(index, stats, itunes, expander)

    def resolve(self, track_id: int | None = None, title: str | None = None,
                artist: str | None = None, country: str | None = None) -> tuple[IndexedTrack, bool]:
        """Returns (track, was_indexed_on_demand)."""
        if track_id is not None and (found := self.index.by_id(track_id)):
            return found, False
        if title and (found := self.index.by_title_artist(title, artist or "")):
            return found, False

        # Not indexed: find it in the user's storefront (then the default one) and analyze it now.
        track = None
        if track_id is not None:
            track = self.itunes.lookup(track_id, country) or (self.itunes.lookup(track_id) if country else None)
        if track is None and title:
            track = self.itunes.search_song(title, artist or "", country)
            if track is None and country and country != self.itunes.country:
                track = self.itunes.search_song(title, artist or "")
        if track is None:
            raise SongNotFound("Song not found in the iTunes catalog, or it has no preview.")
        if found := self.index.by_id(track.track_id) or self.index.by_title_artist(track.title, track.artist):
            return found, False

        audio = download_preview(track)
        if audio is None:
            raise SongNotFound("Couldn't download a preview for this song.")
        raw = features.extract_cached(track.track_id, audio)
        record = indexed_track(track, raw, tagging.Tag(), source="on_demand")
        tag = tagging.tag_tracks([{**track.to_dict(), "bpm": record.bpm, "energy": record.energy,
                                   "onset_rate": record.onset_rate}])[track.track_id]
        record.context, record.mood_tags, record.confidence = tag.context, tag.mood_tags, tag.confidence
        # New tracks use the saved normalization stats so existing vectors stay valid.
        vector = features.transform(raw, self.stats)[0]
        return self.index.add(record, vector), True

    def similar(self, track_id: int | None = None, title: str | None = None, artist: str | None = None,
                limit: int = 10, explain: bool = False, country: str | None = None) -> dict:
        started = time.perf_counter()
        country = (country or self.itunes.country).lower()
        query, added = self.resolve(track_id, title, artist, country)
        query_vector = self.index.matrix[query.row]

        explain_error: str | None = None
        reasons: dict[int, str | None] = {}
        if explain:
            pool = rank(self.index, query, query_vector, limit=int(config.SETTINGS["rerank"]["candidates"]))
            try:
                refined = rerank(query, pool, limit=limit)
                results = [scored for scored, _ in refined]
                reasons = {scored.track.track_id: reason for scored, reason in refined}
            except Exception as error:  # noqa: BLE001 - fall back to the default ranking
                log.warning("Explain mode failed: %s", error)
                explain_error = str(error)
                results = pool[:limit]
        else:
            results = rank(self.index, query, query_vector, limit=limit)

        # Grow the index around this song in the background; clients re-query while expanding.
        expanding = self.expander.request(query, country) if self.expander else False

        return {
            "query": query.to_api(),
            "results": [self._result(item, reasons.get(item.track.track_id)) for item in results],
            "weights": {k: config.SETTINGS["score"][k] for k in ("audio", "tags", "metadata", "tempo")},
            "indexed_on_demand": added,
            "expanding": expanding,
            "index_size": len(self.index),
            "explained": explain and explain_error is None,
            "explain_error": explain_error,
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    @staticmethod
    def _result(item: Scored, reason: str | None) -> dict:
        return {
            "track": item.track.to_api(),
            "score": round(item.breakdown.total, 4),
            "breakdown": item.breakdown.to_dict(),
            "reason": reason,
        }
