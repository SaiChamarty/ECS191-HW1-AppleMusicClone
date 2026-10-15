"""Evaluates ranking quality against pairs you consider similar.

    python -m similarity.evaluate pairs.csv

pairs.csv columns: song_a, song_b. Each cell is "Title - Artist" (split on the
last " - ") or a numeric iTunes trackId. For each pair the query runs for
song_a over the whole index and reports where song_b lands.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from .scoring import rank
from .service import SimilarityService, SongNotFound


def parse_song(cell: str) -> dict:
    cell = cell.strip()
    if cell.isdigit():
        return {"track_id": int(cell)}
    title, separator, artist = cell.rpartition(" - ")
    return {"title": title, "artist": artist} if separator else {"title": cell, "artist": ""}


def evaluate(service: SimilarityService, pairs: list[tuple[str, str]], top_k: int = 10) -> dict:
    index = service.index
    rows: list[dict] = []
    for song_a, song_b in pairs:
        row = {"song_a": song_a, "song_b": song_b, "rank": None, "error": None}
        try:
            query, _ = service.resolve(**parse_song(song_a))
            partner, _ = service.resolve(**parse_song(song_b))
        except SongNotFound as error:
            row["error"] = str(error)
            rows.append(row)
            continue
        # Score every indexed track so ranks beyond the candidate pool are exact.
        ranking = rank(index, query, index.matrix[query.row], limit=len(index), candidates=len(index))
        position = next((i for i, s in enumerate(ranking, start=1) if s.track.song_key == partner.song_key), None)
        row["rank"] = position
        row["partner"] = ranking[position - 1] if position else None
        row["cutoff"] = ranking[top_k - 1] if len(ranking) >= top_k else None
        rows.append(row)

    ranked = [r["rank"] for r in rows if r["rank"] is not None]
    return {
        "rows": rows,
        "evaluated": len(ranked),
        "mean_rank": sum(ranked) / len(ranked) if ranked else None,
        "hit_rate": sum(1 for r in ranked if r <= top_k) / len(ranked) if ranked else None,
        "top_k": top_k,
        "index_size": len(index),
    }


def _fmt(breakdown) -> str:
    return (f"total {breakdown.total:.3f} = audio {breakdown.audio:.3f}, tags {breakdown.tags:.3f}, "
            f"meta {breakdown.metadata:.3f}, tempo {breakdown.tempo:.3f}")


def report(result: dict) -> str:
    lines = [f"{'rank':>5}  pair"]
    for row in result["rows"]:
        rank_text = str(row["rank"]) if row["rank"] else "—"
        lines.append(f"{rank_text:>5}  {row['song_a']}  →  {row['song_b']}" + (f"   ({row['error']})" if row["error"] else ""))
    lines.append("")
    if result["evaluated"]:
        lines.append(f"Pairs evaluated: {result['evaluated']} (index size {result['index_size']})")
        lines.append(f"Mean rank of partner: {result['mean_rank']:.1f}  (random ≈ {result['index_size'] / 2:.0f})")
        lines.append(f"Partner in top {result['top_k']}: {result['hit_rate'] * 100:.0f}%")
    failures = [r for r in result["rows"] if r["rank"] and r["rank"] > result["top_k"]]
    if failures:
        lines.append("")
        lines.append(f"Misses (partner outside top {result['top_k']}): partner vs. #{result['top_k']} score")
        for row in failures:
            lines.append(f"  {row['song_a']} → {row['song_b']} (rank {row['rank']})")
            lines.append(f"    partner: {_fmt(row['partner'].breakdown)}")
            if row["cutoff"]:
                lines.append(f"    #{result['top_k']} {row['cutoff'].track.title}: {_fmt(row['cutoff'].breakdown)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairs", type=Path)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    with args.pairs.open(newline="", encoding="utf-8") as handle:
        pairs = [(r["song_a"], r["song_b"]) for r in csv.DictReader(handle) if r.get("song_a") and r.get("song_b")]
    print(report(evaluate(SimilarityService.load(), pairs, args.top_k)))


if __name__ == "__main__":
    main()
