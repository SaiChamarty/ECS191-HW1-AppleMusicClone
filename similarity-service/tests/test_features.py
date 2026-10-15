import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from similarity import features

SR = features.SAMPLE_RATE


def click_track(bpm: float, seconds: float = 20.0, tone: float = 440.0) -> np.ndarray:
    """Decaying tone bursts on every beat, plus a quiet sustained tone."""
    t = np.arange(int(SR * seconds)) / SR
    signal = 0.05 * np.sin(2 * np.pi * tone * t)
    burst_length = int(0.05 * SR)
    envelope = np.exp(-np.linspace(0, 8, burst_length))
    burst = envelope * np.sin(2 * np.pi * 1000 * np.arange(burst_length) / SR)
    for start in np.arange(0, seconds, 60.0 / bpm):
        index = int(start * SR)
        end = min(index + burst_length, len(signal))
        signal[index:end] += burst[: end - index]
    return signal.astype(np.float32)


def test_vector_layout_is_fixed():
    assert features.DIMENSIONS == 78
    assert len(features.FEATURE_NAMES) == len(set(features.FEATURE_NAMES)) == 78
    assert features.FEATURE_NAMES[features.BPM_INDEX] == "bpm"
    assert features.FEATURE_NAMES.count("chroma_0") == 1


def test_extract_features_shape_and_tempo():
    vector = features.extract_features(click_track(120))
    assert vector.shape == (78,)
    assert vector.dtype == np.float32
    assert np.all(np.isfinite(vector))
    bpm = vector[features.BPM_INDEX]
    # Beat trackers may lock to half/double time; log2 BPM makes those equivalent.
    assert min(abs(np.log2(bpm / 120) - k) for k in (-1, 0, 1)) < 0.05
    assert vector[features.FEATURE_NAMES.index("log2_bpm")] == pytest.approx(np.log2(bpm), rel=1e-5)
    assert vector[features.ONSET_RATE_INDEX] == pytest.approx(2.0, abs=0.5)


def test_energy_curve_is_resampled_and_scaled():
    fade_in = click_track(100) * np.linspace(0.1, 1.0, int(SR * 20), dtype=np.float32)
    vector = features.extract_features(fade_in)
    start = features.FEATURE_NAMES.index("energy_curve_0")
    curve = vector[start : start + features.ENERGY_SEGMENTS]
    assert curve.max() == pytest.approx(1.0)
    assert curve[-1] > curve[0]


def test_faster_music_has_higher_onset_rate():
    slow = features.extract_features(click_track(70))
    fast = features.extract_features(click_track(160))
    assert fast[features.ONSET_RATE_INDEX] > slow[features.ONSET_RATE_INDEX]


def test_rejects_short_or_silent_audio():
    with pytest.raises(ValueError):
        features.extract_features(np.zeros(SR // 2, dtype=np.float32))
    with pytest.raises(ValueError):
        features.extract_features(np.zeros(SR * 5, dtype=np.float32))


def test_normalizer_zscores_weights_and_l2_normalizes():
    rng = np.random.default_rng(0)
    raw = rng.normal(loc=50, scale=10, size=(40, features.DIMENSIONS)).astype(np.float32)
    raw[:, 5] = 3.0  # constant column must not divide by zero
    stats = features.fit_normalizer(raw)
    matrix = features.transform(raw, stats)
    assert matrix.shape == raw.shape
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)
    assert np.all(np.isfinite(matrix))
    assert stats["std"][5] == 1.0
    # New tracks reuse the saved stats rather than refitting.
    single = features.transform(raw[0], stats)
    assert np.allclose(single[0], matrix[0], atol=1e-6)


def test_group_scales_balance_group_sizes():
    scales = features.group_scales({"rhythm": 1, "energy": 1, "spectral": 1, "mfcc": 1, "chroma": 1})
    groups = np.array(features.FEATURE_GROUPS)
    # With equal weights, every group contributes the same total squared weight.
    for group in set(features.FEATURE_GROUPS):
        assert np.sum(scales[groups == group] ** 2) == pytest.approx(1.0)


def test_extract_cached_reuses_saved_vector(tmp_path):
    audio = tmp_path / "clip.wav"
    sf.write(audio, click_track(110, seconds=8), SR)
    first = features.extract_cached(1, audio, feature_dir=tmp_path / "features")
    audio.unlink()  # a cache hit must not need the audio again
    second = features.extract_cached(1, audio, feature_dir=tmp_path / "features")
    assert np.array_equal(first, second)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_decode_audio_handles_aac(tmp_path):
    wav, m4a = tmp_path / "clip.wav", tmp_path / "clip.m4a"
    sf.write(wav, click_track(120, seconds=4), SR)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac", str(m4a)], check=True)
    y = features.decode_audio(m4a)
    assert y.dtype == np.float32
    assert abs(len(y) / SR - 4.0) < 0.2
