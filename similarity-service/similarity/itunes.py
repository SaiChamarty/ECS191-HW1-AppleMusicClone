"""iTunes Search/Lookup API client: throttled, retried, raw responses cached on disk.

No API key is needed. Apple allows roughly 20 requests per minute, so requests
are spaced by `min_interval_seconds` and retried with exponential backoff on
403/429/5xx and network errors.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from . import config
from .textutil import normalize_artist, normalize_title, song_key

log = logging.getLogger(__name__)

BASE_URL = "https://itunes.apple.com"
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


@dataclass
class Track:
    track_id: int
    title: str
    artist: str
    album: str
    genre: str
    release_date: str
    year: int
    duration_ms: int
    preview_url: str
    artwork_url: str

    @property
    def key(self) -> str:
        return song_key(self.title, self.artist)

    def to_dict(self) -> dict:
        return asdict(self)


def track_from_result(result: dict) -> Track | None:
    """Converts an iTunes result to a Track; None if it isn't a song with a preview."""
    if result.get("kind") != "song" or not result.get("previewUrl") or not result.get("trackId"):
        return None
    release = str(result.get("releaseDate") or "")
    year = int(release[:4]) if release[:4].isdigit() else 0
    artwork = str(result.get("artworkUrl100") or "")
    return Track(
        track_id=int(result["trackId"]),
        title=str(result.get("trackName") or ""),
        artist=str(result.get("artistName") or ""),
        album=str(result.get("collectionName") or ""),
        genre=str(result.get("primaryGenreName") or ""),
        release_date=release,
        year=year,
        duration_ms=int(result.get("trackTimeMillis") or 0),
        preview_url=str(result["previewUrl"]),
        # 100px thumbnails can be requested at a larger size by URL.
        artwork_url=artwork.replace("100x100bb", "600x600bb"),
    )


# Alternate recordings to avoid unless the request asks for them.
_ALTERNATE_VERSION = re.compile(
    r"\b(?:remix(?:es)?|karaoke|covers?|tribute|instrumental|originally performed|in the style of|"
    r"backing tracks?|sped up|slowed|8[- ]?bit|lullaby|piano version|acoustic|live|reprise|re-?recorded|"
    r"made famous|lo-?fi|flip|mashup|rework|reimagined|nightcore|mix)\b",
    re.IGNORECASE,
)


def _word_subset(a: str, b: str) -> bool:
    """Whole-word containment either way ("bob marley" ⊂ "bob marley the wailers").

    Scripts written without spaces (e.g. Japanese) fall back to substring
    containment of at least 2 characters.
    """
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a or not words_b:
        return False
    if words_a <= words_b or words_b <= words_a:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 2 and " " not in shorter and not shorter.isascii() and shorter in longer


def best_match(results: list[dict], title: str, artist: str) -> Track | None:
    """Picks the result whose normalized title/artist best match the request.

    When an artist is given it must match; covers, karaoke, remixes and live
    versions lose to the original unless the requested title names them.
    """
    want_title, want_artist = normalize_title(title), normalize_artist(artist)
    best: tuple[int, Track] | None = None
    for result in results:
        track = track_from_result(result)
        if track is None:
            continue
        got_title, got_artist = normalize_title(track.title), normalize_artist(track.artist)
        score = 0
        if got_title == want_title:
            score += 4
        elif _word_subset(want_title, got_title):
            score += 2
        else:
            continue
        if want_artist:
            if got_artist == want_artist:
                score += 3
            elif _word_subset(want_artist, got_artist):
                score += 2
            else:
                continue
        described = f"{track.title} {result.get('collectionName', '')} {track.artist}"
        if _ALTERNATE_VERSION.search(described) and not _ALTERNATE_VERSION.search(title):
            score -= 3
        # Ties keep iTunes' relevance order.
        if score >= 4 and (best is None or score > best[0]):
            best = (score, track)
    return best[1] if best else None


class ITunesClient:
    def __init__(
        self,
        cache_dir: Path = config.ITUNES_CACHE_DIR,
        settings: dict | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        settings = settings or config.SETTINGS["itunes"]
        self.cache_dir = cache_dir
        self.country = settings["country"]
        self.min_interval = float(settings["min_interval_seconds"])
        self.max_retries = int(settings["max_retries"])
        self.backoff_base = float(settings["backoff_base_seconds"])
        self.http = http or httpx.Client(timeout=20.0, follow_redirects=True)
        self._lock = threading.Lock()
        self._last_request = 0.0

    def search_song(self, title: str, artist: str, country: str | None = None, limit: int = 25) -> Track | None:
        params = {
            "term": f"{title} {artist}".strip(),
            "media": "music",
            "entity": "song",
            "limit": str(limit),
            "country": country or self.country,
        }
        payload = self._get("/search", params)
        return best_match(payload.get("results", []), title, artist)

    def lookup(self, track_id: int, country: str | None = None) -> Track | None:
        result = self.lookup_raw(track_id, country)
        return track_from_result(result) if result else None

    def lookup_raw(self, track_id: int, country: str | None = None) -> dict | None:
        """The raw iTunes result (includes artistId, primaryGenreName)."""
        payload = self._get("/lookup", {"id": str(track_id), "country": country or self.country})
        for result in payload.get("results", []):
            if result.get("trackId") == track_id:
                return result
        return None

    def lookup_many(self, track_ids: list[int], country: str | None = None) -> list[Track]:
        """Batch lookup (one request per 150 IDs); skips IDs without previews."""
        tracks: list[Track] = []
        for start in range(0, len(track_ids), 150):
            chunk = track_ids[start : start + 150]
            payload = self._get("/lookup", {"id": ",".join(map(str, chunk)), "country": country or self.country})
            tracks += [t for r in payload.get("results", []) if (t := track_from_result(r))]
        return tracks

    def artist_songs(self, artist_id: int, country: str | None = None, limit: int = 25) -> list[Track]:
        payload = self._get(
            "/lookup", {"id": str(artist_id), "entity": "song", "limit": str(limit), "country": country or self.country}
        )
        return [t for r in payload.get("results", []) if (t := track_from_result(r))]

    def genre_songs(self, genre: str, country: str | None = None, limit: int = 50) -> list[Track]:
        """Songs filed under a genre name (iTunes `genreIndex` search); any language or region."""
        if not genre:
            return []
        payload = self._get("/search", {
            "term": genre, "media": "music", "entity": "song", "attribute": "genreIndex",
            "limit": str(limit), "country": country or self.country,
        })
        return [t for r in payload.get("results", []) if (t := track_from_result(r))]

    def chart_ids(self, country: str | None = None, genre_id: int | None = None, limit: int = 100) -> list[int]:
        """Top-song chart track IDs for a storefront (optionally one genre). Cached per day."""
        country = country or self.country
        genre = f"/genre={genre_id}" if genre_id else ""
        payload = self._get(f"/{country}/rss/topsongs/limit={limit}{genre}/json", {}, cache_tag=time.strftime("%Y-%m-%d"))
        entries = payload.get("feed", {}).get("entry", [])
        if isinstance(entries, dict):  # a one-entry feed isn't wrapped in a list
            entries = [entries]
        ids: list[int] = []
        for entry in entries:
            raw_id = entry.get("id", {}).get("attributes", {}).get("im:id") if isinstance(entry, dict) else None
            if raw_id and str(raw_id).isdigit():
                ids.append(int(raw_id))
        return ids

    def music_genre_ids(self) -> dict[str, int]:
        """Music genre and subgenre names (casefolded) → iTunes genre IDs."""
        payload = self._get("/WebObjects/MZStoreServices.woa/ws/genres", {"id": "34"})
        names: dict[str, int] = {}

        def walk(node: dict) -> None:
            if isinstance(node, dict):
                name, genre_id = node.get("name"), node.get("id")
                if name and str(genre_id).isdigit():
                    names.setdefault(str(name).casefold(), int(genre_id))
                for child in (node.get("subgenres") or {}).values():
                    walk(child)

        for node in payload.values():
            walk(node)
        return names

    def _get(self, path: str, params: dict, cache_tag: str | None = None) -> dict:
        # cache_tag (e.g. today's date) expires entries that change, like charts.
        material = [path, params] if cache_tag is None else [path, params, cache_tag]
        cache_key = hashlib.sha1(json.dumps(material, sort_keys=True).encode()).hexdigest()
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self.http.get(BASE_URL + path, params=params)
                if response.status_code in RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}", request=response.request, response=response
                    )
                response.raise_for_status()
                payload = response.json()
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status is not None and status not in RETRYABLE_STATUS:
                    raise
                last_error = error
                delay = self.backoff_base * (2**attempt) + random.uniform(0, 1)
                log.warning("iTunes %s failed (%s); retrying in %.1fs", path, error, delay)
                time.sleep(delay)
        raise RuntimeError(f"iTunes request failed after {self.max_retries + 1} attempts") from last_error

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
