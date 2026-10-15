"""Fixed-length audio feature vectors (librosa) and index-wide normalization.

Vector layout (78 dims), grouped so groups can be weighted in settings.toml:
  rhythm   (4):  bpm, log2(bpm), beat strength, onset rate
  energy   (12): rms mean, rms std, rms curve resampled to 10 segments
  spectral (10): centroid, rolloff, bandwidth, flatness, zero crossing rate (mean, std each)
  mfcc     (40): 20 MFCC means, 20 MFCC stds
  chroma   (12): 12-bin chroma means

Nothing here is specific to a musical tradition: no key, scale, or genre priors.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import librosa
import numpy as np

from . import config

SAMPLE_RATE = 22050
ANALYSIS_SECONDS = 30
ENERGY_SEGMENTS = 10
N_MFCC = 20
MIN_BPM = 30.0

FEATURE_NAMES: list[str] = (
    ["bpm", "log2_bpm", "beat_strength", "onset_rate"]
    + ["rms_mean", "rms_std"]
    + [f"energy_curve_{i}" for i in range(ENERGY_SEGMENTS)]
    + [f"{name}_{stat}" for name in ("centroid", "rolloff", "bandwidth", "flatness", "zcr") for stat in ("mean", "std")]
    + [f"mfcc_mean_{i}" for i in range(N_MFCC)]
    + [f"mfcc_std_{i}" for i in range(N_MFCC)]
    + [f"chroma_{i}" for i in range(12)]
)
FEATURE_GROUPS: list[str] = ["rhythm"] * 4 + ["energy"] * 12 + ["spectral"] * 10 + ["mfcc"] * 40 + ["chroma"] * 12
DIMENSIONS = len(FEATURE_NAMES)
assert len(FEATURE_GROUPS) == DIMENSIONS

BPM_INDEX = FEATURE_NAMES.index("bpm")
ENERGY_INDEX = FEATURE_NAMES.index("rms_mean")
ONSET_RATE_INDEX = FEATURE_NAMES.index("onset_rate")


def decode_audio(path: Path, sr: int = SAMPLE_RATE, seconds: int = ANALYSIS_SECONDS) -> np.ndarray:
    """Decodes any audio file (AAC previews included) to mono float32 at `sr`."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-t", str(seconds), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        )
        return np.frombuffer(result.stdout, dtype=np.float32).copy()
    # Without ffmpeg, libsndfile handles WAV/FLAC/OGG/MP3 but not AAC.
    y, _ = librosa.load(path, sr=sr, mono=True, duration=seconds)
    return y.astype(np.float32)


def _resample_curve(values: np.ndarray, segments: int) -> np.ndarray:
    chunks = np.array_split(values, segments)
    curve = np.array([chunk.mean() if chunk.size else 0.0 for chunk in chunks], dtype=np.float64)
    peak = curve.max()
    # Shape only; overall loudness is already captured by rms_mean.
    return curve / peak if peak > 0 else curve


def extract_features(y: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Returns the raw (un-normalized) 78-dim feature vector for a mono signal."""
    y = np.asarray(y, dtype=np.float32)[: sr * ANALYSIS_SECONDS]
    if y.size < sr * 2:
        raise ValueError("audio is shorter than 2 seconds")
    if not np.any(y):
        raise ValueError("audio is silent")
    duration = y.size / sr

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    bpm = max(float(np.atleast_1d(tempo)[0]), MIN_BPM)
    mean_onset = float(onset_env.mean()) + 1e-9
    beat_strength = float(onset_env[beats].mean() / mean_onset) if len(beats) else 0.0
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    onset_rate = len(onsets) / duration

    spectrum = np.abs(librosa.stft(y))
    rms = librosa.feature.rms(S=spectrum)[0]
    centroid = librosa.feature.spectral_centroid(S=spectrum, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=spectrum, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=spectrum, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=spectrum)[0]
    zcr = librosa.feature.zero_crossing_rate(y)[0]
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC)
    chroma = librosa.feature.chroma_stft(S=spectrum**2, sr=sr)

    vector = np.concatenate(
        [
            [bpm, np.log2(bpm), beat_strength, onset_rate],
            [rms.mean(), rms.std()],
            _resample_curve(rms, ENERGY_SEGMENTS),
            [stat for series in (centroid, rolloff, bandwidth, flatness, zcr) for stat in (series.mean(), series.std())],
            mfcc.mean(axis=1),
            mfcc.std(axis=1),
            chroma.mean(axis=1),
        ]
    ).astype(np.float32)
    if vector.shape != (DIMENSIONS,) or not np.all(np.isfinite(vector)):
        raise ValueError("feature extraction produced a non-finite vector")
    return vector


def feature_path(track_id: int, feature_dir: Path = config.FEATURE_DIR) -> Path:
    return feature_dir / f"{track_id}.npy"


def extract_cached(track_id: int, audio_path: Path, feature_dir: Path = config.FEATURE_DIR) -> np.ndarray:
    """Per-track feature cache so reruns skip finished tracks."""
    path = feature_path(track_id, feature_dir)
    if path.exists():
        cached = np.load(path)
        if cached.shape == (DIMENSIONS,):
            return cached
    vector = extract_features(decode_audio(audio_path))
    feature_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, vector)
    return vector


# MARK: Normalization


def group_scales(group_weights: dict[str, float] | None = None) -> np.ndarray:
    """Per-dimension multiplier: group weight / sqrt(group size)."""
    weights = group_weights or config.SETTINGS["features"]["group_weights"]
    sizes = {group: FEATURE_GROUPS.count(group) for group in set(FEATURE_GROUPS)}
    return np.array([float(weights[g]) / np.sqrt(sizes[g]) for g in FEATURE_GROUPS], dtype=np.float32)


def fit_normalizer(raw: np.ndarray) -> dict:
    """Z-score stats across the index (std of constant columns is set to 1)."""
    mean = raw.mean(axis=0)
    std = raw.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return {
        "feature_names": FEATURE_NAMES,
        "mean": mean.astype(float).tolist(),
        "std": std.astype(float).tolist(),
        "scales": group_scales().astype(float).tolist(),
        "count": int(raw.shape[0]),
    }


def transform(raw: np.ndarray, stats: dict) -> np.ndarray:
    """Z-score with saved stats, apply group weights, then L2-normalize rows."""
    matrix = np.atleast_2d(raw).astype(np.float32)
    mean = np.asarray(stats["mean"], dtype=np.float32)
    std = np.asarray(stats["std"], dtype=np.float32)
    scales = np.asarray(stats["scales"], dtype=np.float32)
    z = (matrix - mean) / std * scales
    norms = np.linalg.norm(z, axis=1, keepdims=True)
    return (z / np.where(norms < 1e-12, 1.0, norms)).astype(np.float32)


def save_stats(stats: dict, path: Path = config.NORM_STATS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def load_stats(path: Path = config.NORM_STATS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
