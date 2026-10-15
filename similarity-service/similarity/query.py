"""Command-line query against the local index (same code path as the API).

    python -m similarity.query "Midnight City" "M83" [--explain] [--json]
    python -m similarity.query --track-id 509665325
"""

from __future__ import annotations

import argparse
import json
import logging

from .service import SimilarityService


def format_results(response: dict) -> str:
    query = response["query"]
    lines = [
        f"Query: {query['title']} — {query['artist']} ({query['genre']}, {query['year'] or '?'}, "
        f"{query['bpm']} BPM, context={query['context']})"
        + ("  [indexed on demand]" if response["indexed_on_demand"] else ""),
        f"{'#':>2}  {'score':>5}  {'audio':>5} {'tags':>5} {'meta':>5} {'tempo':>5}  song",
    ]
    for number, result in enumerate(response["results"], start=1):
        track, parts = result["track"], result["breakdown"]
        lines.append(
            f"{number:>2}  {result['score']:.3f}  {parts['audio']:.3f} {parts['tags']:.3f} "
            f"{parts['metadata']:.3f} {parts['tempo']:.3f}  {track['title']} — {track['artist']} "
            f"({track['genre']}, {track['year'] or '?'}, {track['bpm']} BPM)"
        )
        if result.get("reason"):
            lines.append(f"{'':>9}↳ {result['reason']}")
    if response.get("explain_error"):
        lines.append(f"(explain mode failed, default ranking shown: {response['explain_error']})")
    lines.append(f"took {response['took_ms']} ms")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Find songs similar to a song.")
    parser.add_argument("title", nargs="?")
    parser.add_argument("artist", nargs="?", default="")
    parser.add_argument("--track-id", type=int)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--explain", action="store_true", help="One Claude call to refine and explain (needs ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Print the raw API response.")
    args = parser.parse_args()
    if not args.title and args.track_id is None:
        parser.error("give a title (and artist) or --track-id")
    logging.basicConfig(level=logging.WARNING)

    service = SimilarityService.load()
    response = service.similar(track_id=args.track_id, title=args.title, artist=args.artist,
                               limit=args.limit, explain=args.explain)
    print(json.dumps(response, indent=2, ensure_ascii=False) if args.json else format_results(response))


if __name__ == "__main__":
    main()
