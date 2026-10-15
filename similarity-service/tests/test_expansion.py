import json

import numpy as np

from similarity import expansion, features
from similarity.expansion import Expander, Job
from similarity.itunes import ITunesClient, Track
from similarity.store import Index
from tests.test_scoring import make_track, unit

SETTINGS = {"enabled": True, "artist_songs": 25, "chart_size": 100, "genre_songs": 50, "max_new_tracks": 3,
            "max_queue": 2, "workers": 1, "keep_previews": False}


def track(track_id: int, title: str, artist: str = "Artist") -> Track:
    return Track(track_id, title, artist, "Album", "K-Pop", "2020-01-01", 2020, 200000,
                 "https://example.com/p.m4a", "https://example.com/a.jpg")


def song_result(track_id: int, title: str, artist: str = "Artist") -> dict:
    return {"kind": "song", "trackId": track_id, "trackName": title, "artistName": artist, "artistId": 7,
            "collectionName": "Album", "previewUrl": "https://example.com/p.m4a", "primaryGenreName": "K-Pop",
            "releaseDate": "2020-01-01T00:00:00Z", "artworkUrl100": "https://example.com/100x100bb.jpg"}


class FakeHTTPClient(ITunesClient):
    """ITunesClient with canned responses keyed by path, no network or throttle."""

    def __init__(self, responses: dict):
        super().__init__(cache_dir=None)
        self.responses = responses
        self.requests: list[tuple[str, dict]] = []

    def _get(self, path, params, cache_tag=None):
        self.requests.append((path, params))
        response = self.responses.get(path, {})
        return response(params) if callable(response) else response


def test_chart_ids_parses_feed_and_single_entry():
    feed = {"feed": {"entry": [{"id": {"attributes": {"im:id": "11"}}}, {"id": {"attributes": {"im:id": "22"}}}]}}
    client = FakeHTTPClient({"/kr/rss/topsongs/limit=100/genre=51/json": feed,
                             "/jp/rss/topsongs/limit=5/json": {"feed": {"entry": {"id": {"attributes": {"im:id": "33"}}}}}})
    assert client.chart_ids("kr", 51, 100) == [11, 22]
    assert client.chart_ids("jp", None, 5) == [33]


def test_lookup_many_batches_by_150_and_skips_previewless():
    def lookup(params):
        ids = [int(i) for i in params["id"].split(",")]
        return {"results": [song_result(i, f"S{i}") if i % 2 else {**song_result(i, "x"), "previewUrl": None} for i in ids]}

    client = FakeHTTPClient({"/lookup": lookup})
    found = client.lookup_many(list(range(1, 321)), "in")
    assert len(client.requests) == 3
    assert all(params["country"] == "in" for _, params in client.requests)
    assert len(found) == 160 and all(t.track_id % 2 for t in found)


def test_music_genre_ids_walks_subgenres():
    tree = {"34": {"name": "Music", "id": "34", "subgenres": {
        "51": {"name": "K-Pop", "id": "51"},
        "1122": {"name": "Brazilian", "id": "1122", "subgenres": {"1220": {"name": "MPB", "id": "1220"}}},
    }}}
    names = FakeHTTPClient({"/WebObjects/MZStoreServices.woa/ws/genres": tree}).music_genre_ids()
    assert names["k-pop"] == 51 and names["mpb"] == 1220 and names["music"] == 34


def make_index(tmp_path, count: int = 3) -> Index:
    index = Index(tmp_path / "index.sqlite", tmp_path / "vectors.npy")
    rng = np.random.default_rng(3)
    tracks = [make_track(i + 1, f"Song {i}", "Someone", i) for i in range(count)]
    index.write_all(tracks, np.vstack([unit(rng.normal(size=features.DIMENSIONS)) for _ in tracks]))
    return index


def test_add_many_skips_duplicates_and_persists(tmp_path):
    index = make_index(tmp_path)
    rng = np.random.default_rng(4)
    new = [make_track(10, "New", "A"), make_track(11, "Song 0", "Someone"),  # same song as an indexed one
           make_track(12, "New (Live)", "A"), make_track(1, "Dup id", "B")]
    vectors = np.vstack([unit(rng.normal(size=features.DIMENSIONS)) for _ in new])
    added = index.add_many(new, vectors)
    assert [t.track_id for t in added] == [10]
    assert added[0].row == 3 and index.matrix.shape[0] == 4
    reloaded = Index.load(tmp_path / "index.sqlite", tmp_path / "vectors.npy")
    assert len(reloaded) == 4 and np.allclose(reloaded.matrix[3], vectors[0])


def test_expander_collects_artist_chart_and_genre_candidates(tmp_path, monkeypatch):
    index = make_index(tmp_path)
    client = FakeHTTPClient({
        "/lookup": lambda p: {"results": [song_result(500, "Query")]} if p["id"] == "500" else
                             {"results": [song_result(int(i), f"Chart {i}") for i in p["id"].split(",")]}
                             if "," in p["id"] or p.get("entity") is None else
                             {"results": [{"wrapperType": "artist"}, song_result(601, "Artist song"),
                                          song_result(602, "Song 0", "Someone")]},
        "/WebObjects/MZStoreServices.woa/ws/genres": {"34": {"name": "Music", "id": "34",
                                                             "subgenres": {"51": {"name": "K-Pop", "id": "51"}}}},
        "/kr/rss/topsongs/limit=100/genre=51/json": {"feed": {"entry": [{"id": {"attributes": {"im:id": "701"}}},
                                                                        {"id": {"attributes": {"im:id": "702"}}}]}},
        "/search": {"results": [song_result(801, "Genre song")]},
    })
    captured = {}

    def fake_add(idx, stats, tracks, source, workers, discard_audio):
        captured.update(tracks=tracks, source=source, discard=discard_audio)
        return []

    monkeypatch.setattr(expansion, "add_to_index", fake_add)
    expander = Expander(index, {}, client, SETTINGS)
    expander.expand(Job(500, "kr"))
    titles = [t.title for t in captured["tracks"]]
    # Artist songs first; already-indexed songs skipped; capped at max_new_tracks.
    assert titles == ["Artist song", "Chart 701", "Chart 702"]
    assert captured["source"] == "expansion" and captured["discard"] is True
    assert all(p.get("country") == "kr" for path, p in client.requests if path in ("/lookup", "/search"))

    # Sources already pulled aren't fetched again for the next song.
    before = len(client.requests)
    expander.candidates(Job(500, "kr"))
    assert len(client.requests) == before + 1  # only the query lookup


def test_expander_falls_back_to_default_storefront(tmp_path):
    index = make_index(tmp_path)
    client = FakeHTTPClient({
        "/lookup": lambda p: {"results": [song_result(500, "Query")]} if p["id"] == "500" else
                             {"results": [song_result(int(i), f"US chart {i}") for i in p["id"].split(",")]},
        "/WebObjects/MZStoreServices.woa/ws/genres": {},
        "/kr/rss/topsongs/limit=100/json": {"feed": {}},   # storefront without charts
        "/us/rss/topsongs/limit=100/json": {"feed": {"entry": [{"id": {"attributes": {"im:id": "901"}}}]}},
        "/search": lambda p: {"results": [] if p["country"] == "kr" else [song_result(902, "US genre song")]},
    })
    found = Expander(index, {}, client, SETTINGS).candidates(Job(500, "kr"))
    assert [t.title for t in found if t.track_id in (901, 902)] == ["US chart 901", "US genre song"]


def test_expander_request_dedupes_and_caps_queue(tmp_path):
    index = make_index(tmp_path)
    expander = Expander(index, {}, FakeHTTPClient({}), SETTINGS)  # worker not started
    first, second, third = (make_track(i, f"Q{i}", "A") for i in (101, 102, 103))
    assert expander.request(first, "us") is True
    assert expander.request(first, "us") is True and expander._queue.qsize() == 1
    assert expander.request(second, "us") is True
    assert expander.request(third, "us") is False  # max_queue = 2
    assert expander.request(first, "jp") is False   # queue still full
    assert expander.is_expanding(first.track_id, "us")


def test_api_request_validates_country():
    import pytest
    from pydantic import ValidationError

    from similarity.api import SimilarRequest

    assert SimilarRequest(title="Idol", artist="YOASOBI", country="JP").country == "JP"
    with pytest.raises(ValidationError):
        SimilarRequest(title="Idol", country="japan")
    assert json.loads(SimilarRequest(track_id=1).model_dump_json())["country"] == "us"
