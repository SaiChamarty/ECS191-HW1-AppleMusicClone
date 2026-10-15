import json
from types import SimpleNamespace

import pytest

from similarity import tagging
from similarity.itunes import best_match
from similarity.rerank import parse_rerank
from similarity.tagging import TagParseError, build_payload, parse_tags, tag_tracks
from similarity.textutil import first_json_array

IDS = {1, 2, 3}


def test_first_json_array_skips_prose_fences_and_bracketed_strings():
    text = 'Sure! Here you go [not json]\n```json\n[{"trackId": 1, "context": "sad [x]"}]\n```\nDone [2].'
    assert json.loads(first_json_array(text)) == [{"trackId": 1, "context": "sad [x]"}]
    assert first_json_array("no array here") is None


def test_parse_tags_valid_response():
    text = json.dumps([
        {"trackId": 1, "context": "dance_club", "mood_tags": ["euphoric", "Bright"], "confidence": 0.9},
        {"trackId": "2", "context": "ballad", "mood_tags": [], "confidence": "0.7"},
    ])
    tags = parse_tags(text, IDS)
    assert tags[1].context == "dance_club" and tags[1].mood_tags == ["euphoric", "bright"]
    assert tags[2].context == "ballad" and tags[2].confidence == pytest.approx(0.7)
    assert 3 not in tags


def test_parse_tags_sanitizes_bad_values():
    text = json.dumps([
        {"trackId": 1, "context": "made_up_context", "mood_tags": ["a", "b", "c", "d"], "confidence": 0.95},
        {"trackId": 2, "context": "sad", "mood_tags": "not a list", "confidence": 7},
        {"trackId": 3, "context": "unknown", "confidence": 0.9},
        {"trackId": 99, "context": "sad", "confidence": 1},     # not requested
        {"trackId": "abc", "context": "sad"},                    # bad id
        "garbage",
    ])
    tags = parse_tags(text, IDS)
    assert tags[1].context == "unknown" and tags[1].confidence <= 0.3
    assert len(tags[1].mood_tags) <= 3
    assert tags[2].mood_tags == [] and tags[2].confidence == 1.0
    assert tags[3].confidence == pytest.approx(0.3)
    assert set(tags) == {1, 2, 3}


def test_parse_tags_without_array_raises():
    with pytest.raises(TagParseError):
        parse_tags("I can't help with that.", IDS)


def test_payload_is_metadata_only():
    track = {"track_id": 1, "title": "T", "artist": "A", "album": "Al", "genre": "G", "year": 2001,
             "bpm": 120.04, "energy": 0.123456, "onset_rate": 3.14159, "lyrics": "never sent",
             "preview_url": "https://example.com"}
    payload = build_payload([track])[0]
    assert set(payload) == {"trackId", "title", "artist", "album", "genre", "year", "bpm", "energy", "onset_rate"}


class FakeClient:
    """Mimics client.messages.create, returning scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else "[]"
        if callable(reply):
            reply = reply(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=reply)])


def echo_tags(kwargs) -> str:
    sent = json.loads(kwargs["messages"][0]["content"])
    return json.dumps([{"trackId": t["trackId"], "context": "chill", "mood_tags": ["calm"], "confidence": 0.8}
                       for t in sent])


def tracks(count: int) -> list[dict]:
    return [{"track_id": i, "title": f"T{i}", "artist": "A", "bpm": 100, "energy": 0.1, "onset_rate": 2}
            for i in range(1, count + 1)]


def test_tag_tracks_batches_by_20_and_caches(tmp_path):
    client = FakeClient([echo_tags] * 3)
    result = tag_tracks(tracks(45), client=client, model="test-model", tag_dir=tmp_path)
    assert len(client.calls) == 3
    assert [len(json.loads(c["messages"][0]["content"])) for c in client.calls] == [20, 20, 5]
    assert all(tag.context == "chill" for tag in result.values())
    assert client.calls[0]["model"] == "test-model"

    # Second run is fully cached: no calls.
    again = FakeClient([])
    tag_tracks(tracks(45), client=again, tag_dir=tmp_path)
    assert again.calls == []


def test_tag_tracks_retries_once_then_leaves_unknown_uncached(tmp_path):
    client = FakeClient(["oops, not JSON", "still not JSON"])
    result = tag_tracks(tracks(3), client=client, tag_dir=tmp_path)
    assert len(client.calls) == 2
    assert all(tag.context == "unknown" and tag.confidence == 0 for tag in result.values())
    assert list(tmp_path.iterdir()) == []

    recovered = FakeClient(["garbage", echo_tags])
    result = tag_tracks(tracks(3), client=recovered, tag_dir=tmp_path)
    assert len(recovered.calls) == 2 and result[1].context == "chill"


def test_tag_tracks_retry_only_asks_for_missing_tracks(tmp_path):
    partial = json.dumps([{"trackId": 1, "context": "sad", "mood_tags": [], "confidence": 0.9}])
    client = FakeClient([partial, echo_tags])
    result = tag_tracks(tracks(3), client=client, tag_dir=tmp_path)
    retried = json.loads(client.calls[1]["messages"][0]["content"])
    assert [t["trackId"] for t in retried] == [2, 3]
    assert result[1].context == "sad" and result[2].context == "chill"


def test_tag_tracks_without_key_skips_api(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(tagging, "_make_client", lambda: pytest.fail("must not create a client"))
    result = tag_tracks(tracks(2), tag_dir=tmp_path)
    assert all(tag.context == "unknown" for tag in result.values())


def test_parse_rerank_filters_and_dedupes():
    text = 'Here: [{"trackId": 5, "reason": "Same  tempo"}, {"trackId": 5, "reason": "dup"},' \
           ' {"trackId": 42, "reason": "not a candidate"}, {"trackId": "7", "reason": ""}]'
    assert parse_rerank(text, [5, 7, 9]) == [(5, "Same tempo"), (7, "")]
    with pytest.raises(ValueError):
        parse_rerank("[]", [5])


def test_rerank_uses_one_call_and_fills_from_default_order():
    from similarity.rerank import rerank
    from similarity.scoring import Breakdown, Scored
    from tests.test_scoring import make_track

    query = make_track(100, "Query", "Artist")
    pool = [Scored(make_track(i, f"Song {i}", "X", i), Breakdown(0.5, 0, 0, 0, 1 - i / 100), 0.5) for i in range(1, 16)]
    reply = json.dumps([{"trackId": 7, "reason": "Same tempo and energy."}, {"trackId": 3, "reason": "Close audio."}])
    client = FakeClient([reply])
    results = rerank(query, pool, limit=10, client=client, model="test-rerank")
    assert len(client.calls) == 1 and client.calls[0]["model"] == "test-rerank"
    sent = json.loads(client.calls[0]["messages"][0]["content"])
    assert len(sent["candidates"]) == 15 and "scores" in sent["candidates"][0]
    ids = [scored.track.track_id for scored, _ in results]
    assert ids[:2] == [7, 3] and len(ids) == 10 and len(set(ids)) == 10
    assert results[0][1] == "Same tempo and energy." and results[2][1] is None


def test_rerank_without_key_fails_fast(monkeypatch):
    from similarity.rerank import rerank
    from tests.test_scoring import make_track

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        rerank(make_track(1, "Q", "A"), [], limit=10)


def itunes_result(track_id, title, artist, album="Album", preview=True):
    return {"kind": "song", "trackId": track_id, "trackName": title, "artistName": artist,
            "collectionName": album, "previewUrl": "https://example.com/p.m4a" if preview else None,
            "releaseDate": "2016-08-20T07:00:00Z", "primaryGenreName": "R&B/Soul",
            "artworkUrl100": "https://example.com/100x100bb.jpg"}


def test_best_match_prefers_originals_over_covers():
    results = [
        itunes_result(1, "Redbone (Originally Performed by Childish Gambino) [Karaoke Version]", "Starstruck"),
        itunes_result(2, "Nights", "Blond Piano", album="Piano Tribute to Frank Ocean"),
        itunes_result(3, "nights", "A[way]"),
        itunes_result(4, "Nights", "Frank Ocean", preview=False),
    ]
    assert best_match(results, "Nights", "Frank Ocean") is None
    results.append(itunes_result(5, "Nights", "Frank Ocean", album="Blonde"))
    match = best_match(results, "Nights", "Frank Ocean")
    assert match.track_id == 5 and match.year == 2016
    assert match.artwork_url.endswith("600x600bb.jpg")


def test_best_match_works_across_scripts():
    results = [itunes_result(1, "アイドル", "YOASOBI"), itunes_result(2, "Idol", "YOASOBI")]
    assert best_match(results, "アイドル", "YOASOBI").track_id == 1
