import numpy as np
import pytest

from similarity import config, features
from similarity.scoring import metadata_match, rank, score_pair, tag_match, tempo_closeness
from similarity.store import Index, IndexedTrack
from similarity.tagging import Tag
from similarity.textutil import normalize_title, song_key


def make_track(track_id: int, title: str, artist: str, row: int = 0, *, genre: str = "Pop", year: int = 2010,
               bpm: float = 120.0, context: str = "unknown", moods=(), confidence: float = 0.0) -> IndexedTrack:
    return IndexedTrack(
        track_id=track_id, row=row, title=title, artist=artist, album="", genre=genre, release_date="",
        year=year, duration_ms=0, preview_url="https://example.com/p.m4a", artwork_url="",
        song_key=song_key(title, artist), bpm=bpm, energy=0.1, onset_rate=2.0,
        context=context, mood_tags=list(moods), confidence=confidence,
    )


def test_score_weights_sum_to_one():
    weights = config.SETTINGS["score"]
    assert sum(weights[k] for k in ("audio", "tags", "metadata", "tempo")) == pytest.approx(1.0)


def test_tempo_treats_half_and_double_time_as_close():
    assert tempo_closeness(120, 120) == pytest.approx(1.0)
    assert tempo_closeness(120, 60) == pytest.approx(1.0)
    assert tempo_closeness(85, 170) == pytest.approx(1.0)
    assert tempo_closeness(120, 90) < 0.1
    assert tempo_closeness(120, 126) > tempo_closeness(120, 140)
    assert tempo_closeness(0, 120) == 0.0


def test_tag_match_prefers_context_and_scales_by_confidence():
    query = Tag("sad", ["melancholy", "slow"], 1.0)
    same_context = Tag("sad", [], 1.0)
    same_moods = Tag("chill", ["melancholy", "slow"], 1.0)
    assert tag_match(query, same_context) > tag_match(query, same_moods) > 0
    assert tag_match(query, Tag("sad", [], 0.25)) == pytest.approx(tag_match(query, same_context) * 0.5)


def test_unknown_context_never_counts_as_a_match():
    assert tag_match(Tag("unknown", [], 0.3), Tag("unknown", [], 0.3)) == 0.0
    assert tag_match(Tag(), Tag("sad", ["x"], 1.0)) == 0.0


def test_metadata_match_components():
    query = make_track(1, "A", "Artist", genre="J-Pop", year=2020)
    assert metadata_match(query, make_track(2, "B", "Artist", genre="J-Pop", year=2023)) == pytest.approx(1.0)
    assert metadata_match(query, make_track(3, "C", "Other", genre="J-Pop", year=2024)) == pytest.approx(0.35)
    assert metadata_match(query, make_track(4, "D", "Other", genre="Rock", year=2019)) == pytest.approx(0.25)
    assert metadata_match(query, make_track(5, "E", "Other", genre="Rock", year=0)) == 0.0


def test_score_pair_is_weighted_sum():
    query = make_track(1, "A", "Artist", bpm=100)
    candidate = make_track(2, "B", "Artist", bpm=100)
    breakdown = score_pair(query, candidate, cosine=0.8)
    weights = config.SETTINGS["score"]
    expected = (weights["audio"] * 0.8 + weights["tags"] * breakdown.tags
                + weights["metadata"] * breakdown.metadata + weights["tempo"] * breakdown.tempo)
    assert breakdown.total == pytest.approx(expected)
    assert score_pair(query, candidate, cosine=-0.4).audio == 0.0


def build_index(tracks: list[IndexedTrack], vectors: np.ndarray) -> Index:
    index = Index()
    index.tracks = tracks
    index.matrix = vectors.astype(np.float32)
    index._reindex()
    return index


def unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_rank_excludes_query_and_duplicate_versions():
    rng = np.random.default_rng(1)
    base = rng.normal(size=features.DIMENSIONS)
    near = lambda scale: unit(base + rng.normal(scale=scale, size=features.DIMENSIONS))  # noqa: E731
    tracks = [
        make_track(1, "Heroes", "David Bowie", 0),
        make_track(2, "Heroes (2017 Remaster)", "David Bowie", 1),      # same song as the query
        make_track(3, "Sound and Vision", "David Bowie", 2),
        make_track(4, "Sound and Vision - Live", "David Bowie", 3),     # duplicate of 3
        make_track(5, "Other Song", "Someone", 4),
    ]
    vectors = np.vstack([unit(base), near(0.01), near(0.1), near(0.12), unit(rng.normal(size=features.DIMENSIONS))])
    index = build_index(tracks, vectors)
    results = rank(index, tracks[0], vectors[0], limit=10)
    ids = [r.track.track_id for r in results]
    assert 1 not in ids and 2 not in ids
    assert ids.count(3) + ids.count(4) == 1
    assert ids[0] in (3, 4)
    assert all(results[i].breakdown.total >= results[i + 1].breakdown.total for i in range(len(results) - 1))


def test_rank_respects_candidate_pool_and_limit():
    rng = np.random.default_rng(2)
    vectors = np.vstack([unit(rng.normal(size=features.DIMENSIONS)) for _ in range(50)])
    tracks = [make_track(i + 1, f"Song {i}", f"Artist {i}", i) for i in range(50)]
    index = build_index(tracks, vectors)
    results = rank(index, tracks[0], vectors[0], limit=10, candidates=20)
    assert len(results) == 10
    cosines = vectors @ vectors[0]
    pool = set(np.argsort(-cosines)[1:21])
    assert all(r.track.row in pool for r in results)


@pytest.mark.parametrize("title, expected", [
    ("Heroes (2017 Remaster)", "heroes"),
    ("Heroes - 2017 Remaster", "heroes"),
    ("Tum Hi Ho (From \"Aashiqui 2\")", "tum hi ho"),
    ("Idol", "idol"),
    ("アイドル", "アイドル"),
    ("Tití Me Preguntó", "tití me preguntó"),
    ("तुम ही हो", "तुम ही हो"),
    ("Chop Suey!", "chop suey"),
])
def test_normalize_title_handles_versions_and_scripts(title, expected):
    assert normalize_title(title) == expected
