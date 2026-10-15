"""Concurrent 30-second preview downloads into the git-ignored cache."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

import httpx

from . import config
from .itunes import Track

log = logging.getLogger(__name__)


def preview_path(track_id: int, preview_dir: Path = config.PREVIEW_DIR) -> Path:
    return preview_dir / f"{track_id}.m4a"


async def _download(
    client: httpx.AsyncClient, track: Track, destination: Path, semaphore: asyncio.Semaphore, retries: int
) -> bool:
    async with semaphore:
        for attempt in range(retries + 1):
            try:
                response = await client.get(track.preview_url)
                response.raise_for_status()
                temporary = destination.with_suffix(".part")
                temporary.write_bytes(response.content)
                temporary.replace(destination)  # atomic: no half-written files on rerun
                return True
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                delay = 2**attempt + random.uniform(0, 1)
                log.warning("Preview %s failed (%s); retrying in %.1fs", track.track_id, error, delay)
                await asyncio.sleep(delay)
    return False


async def download_previews(
    tracks: list[Track],
    preview_dir: Path = config.PREVIEW_DIR,
    concurrency: int | None = None,
    retries: int | None = None,
) -> dict[int, Path]:
    """Downloads missing previews; returns {track_id: path} for every track with audio."""
    settings = config.SETTINGS["itunes"]
    concurrency = concurrency or int(settings["download_concurrency"])
    retries = retries if retries is not None else int(settings["max_retries"])
    preview_dir.mkdir(parents=True, exist_ok=True)

    available: dict[int, Path] = {}
    pending: list[tuple[Track, Path]] = []
    for track in tracks:
        path = preview_path(track.track_id, preview_dir)
        if path.exists() and path.stat().st_size > 0:
            available[track.track_id] = path
        else:
            pending.append((track, path))

    if pending:
        semaphore = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            outcomes = await asyncio.gather(
                *(_download(client, track, path, semaphore, retries) for track, path in pending)
            )
        for (track, path), ok in zip(pending, outcomes):
            if ok:
                available[track.track_id] = path
    log.info("Previews: %d cached, %d downloaded, %d failed",
             len(tracks) - len(pending), sum(1 for (t, _) in pending if t.track_id in available),
             sum(1 for (t, _) in pending if t.track_id not in available))
    return available


def download_preview(track: Track, preview_dir: Path = config.PREVIEW_DIR) -> Path | None:
    """Synchronous single download for on-demand indexing."""
    return asyncio.run(download_previews([track], preview_dir)).get(track.track_id)
