"""Offline indexer. Resumable: every stage caches per track, so reruns only do new work.

    python -m similarity.index --seeds seeds.csv [--skip-tagging] [--workers 4]
    python -m similarity.index --charts us,gb,in,br,mx,jp,kr,ng,za,fr,de,eg --discard-audio

seeds.csv columns: title, artist, country (optional, iTunes storefront, default "us").
--charts adds each storefront's top-song chart (up to --chart-limit songs each),
resolved with batch lookups (one request per 150 songs), to cover many regions fast.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import numpy as np

from . import config, features
from .itunes import ITunesClient, Track
from .pipeline import analyze, indexed_track, tag_records
from .store import Index
from .tagging import Tag

log = logging.getLogger("similarity.index")

# Tracks added after a build (by queries); a rebuild keeps them.
RUNTIME_SOURCES = {"on_demand", "expansion"}


def read_seeds(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("title") or "").strip()]
    return [
        {"title": r["title"].strip(), "artist": (r.get("artist") or "").strip(),
         "country": (r.get("country") or "").strip() or None}
        for r in rows
    ]


def collect_tracks(seeds: list[dict], client: ITunesClient) -> list[Track]:
    """Resolves seeds to tracks with previews; dedupes by trackId and song identity."""
    tracks: list[Track] = []
    seen_ids: set[int] = set()
    seen_keys: set[str] = set()
    for number, seed in enumerate(seeds, start=1):
        try:
            track = client.search_song(seed["title"], seed["artist"], country=seed["country"])
        except Exception as error:  # noqa: BLE001 - one bad seed shouldn't stop the run
            log.warning("[%d/%d] %s – %s: lookup failed (%s)", number, len(seeds), seed["title"], seed["artist"], error)
            continue
        if track is None:
            log.warning("[%d/%d] %s – %s: no match with a preview, skipped",
                        number, len(seeds), seed["title"], seed["artist"])
            continue
        if track.track_id in seen_ids or track.key in seen_keys:
            log.info("[%d/%d] %s – %s: duplicate, skipped", number, len(seeds), track.title, track.artist)
            continue
        seen_ids.add(track.track_id)
        seen_keys.add(track.key)
        tracks.append(track)
        log.info("[%d/%d] %s – %s (%s)", number, len(seeds), track.title, track.artist, track.genre)
    return tracks


def collect_charts(countries: list[str], client: ITunesClient, limit: int) -> list[Track]:
    tracks: list[Track] = []
    for country in countries:
        try:
            ids = client.chart_ids(country, limit=limit)
            found = client.lookup_many(ids, country)
        except Exception as error:  # noqa: BLE001 - one storefront failing shouldn't stop the run
            log.warning("Chart %s failed: %s", country, error)
            continue
        log.info("Chart %s: %d songs, %d with previews", country, len(ids), len(found))
        tracks += found
    return tracks


def dedupe(tracks: list[Track]) -> list[Track]:
    kept: list[Track] = []
    seen: set = set()
    for track in tracks:
        if track.track_id in seen or track.key in seen:
            continue
        seen.update({track.track_id, track.key})
        kept.append(track)
    return kept


def previously_indexed() -> tuple[list[Track], dict[int, str]]:
    """Tracks added by queries since the last build, and their sources."""
    try:
        existing = Index.load()
    except (FileNotFoundError, ValueError):
        return [], {}
    runtime = [t for t in existing.tracks if t.source in RUNTIME_SOURCES]
    if runtime:
        log.info("Keeping %d tracks that were added by queries", len(runtime))
    tracks = [
        Track(t.track_id, t.title, t.artist, t.album, t.genre, t.release_date, t.year, t.duration_ms,
              t.preview_url, t.artwork_url)
        for t in runtime
    ]
    return tracks, {t.track_id: t.source for t in runtime}


def build_index(seeds_path: Path | None, charts: list[str], chart_limit: int = 100, skip_tagging: bool = False,
                workers: int = 4, discard_audio: bool = False) -> Index:
    client = ITunesClient()
    tracks: list[Track] = []
    if seeds_path:
        seeds = read_seeds(seeds_path)
        log.info("Resolving %d seeds via the iTunes Search API (throttled; responses cached)", len(seeds))
        tracks += collect_tracks(seeds, client)
    seeded = len(tracks)
    if charts:
        tracks += collect_charts(charts, client, chart_limit)
    previous, sources = previously_indexed()
    tracks = dedupe(tracks + previous)
    log.info("%d unique tracks (%d from seeds)", len(tracks), seeded)

    analyzed = analyze(tracks, workers, discard_audio)
    if not analyzed:
        raise SystemExit("No tracks could be analyzed.")

    records = [
        indexed_track(t, raw, Tag(), row=i, source=sources.get(t.track_id, "seed"))
        for i, (t, raw) in enumerate(analyzed)
    ]
    tag_records(analyzed, records, skip_tagging)

    raw = np.vstack([vector for _, vector in analyzed])
    stats = features.fit_normalizer(raw)
    features.save_stats(stats)
    index = Index()
    index.write_all(records, features.transform(raw, stats))
    tagged = sum(1 for r in records if r.confidence > 0)
    log.info("Index written: %d tracks (%d tagged) → %s", len(records), tagged, config.DATA_DIR)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=Path, default=config.SERVICE_ROOT / "seeds.csv",
                        help="CSV of title,artist,country (use --seeds '' to skip)")
    parser.add_argument("--charts", default="", help="Comma-separated storefronts whose top-song charts to add")
    parser.add_argument("--chart-limit", type=int, default=100, help="Songs per chart (max 200)")
    parser.add_argument("--skip-tagging", action="store_true", help="Don't call Claude (cached tags still apply).")
    parser.add_argument("--workers", type=int, default=4, help="Processes for feature extraction.")
    parser.add_argument("--discard-audio", action="store_true", help="Delete previews once features are cached.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    charts = [c.strip().lower() for c in args.charts.split(",") if c.strip()]
    seeds = args.seeds if args.seeds and str(args.seeds) not in ("", ".") else None
    build_index(seeds, charts, args.chart_limit, args.skip_tagging, args.workers, args.discard_audio)


if __name__ == "__main__":
    main()
