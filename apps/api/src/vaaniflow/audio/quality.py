"""
Deterministic audio quality analysis (System-Design 04 §4.4).

Frame-energy based measurements on mono float samples in [-1, 1]:

- peak level (dBFS) and clipping detection
- speech ratio: frames clearly above the estimated noise floor
- silence ratio: frames at digital near-silence
- estimated SNR: mean speech-frame level minus noise floor
- noise level and quality class from configurable thresholds

This is an energy heuristic, not a neural VAD or a perceptual quality
model. Its purpose is to replace caller-supplied quality metadata with
measured values and to flag recordings with no usable speech.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from vaaniflow.domain.schemas.common import AudioQualityLevel, NoiseLevel

_EPSILON = 1e-10


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    frame_ms: int = 30
    speech_margin_db: float = 10.0
    speech_floor_dbfs: float = -50.0
    silence_dbfs: float = -60.0
    clip_level: float = 0.999
    clip_min_samples: int = 3
    clip_min_fraction: float = 0.0005
    noise_low_dbfs: float = -50.0
    noise_medium_dbfs: float = -35.0
    min_duration_ms: int = 300
    unusable_speech_ratio: float = 0.05
    poor_speech_ratio: float = 0.15
    good_snr_db: float = 20.0
    acceptable_snr_db: float = 12.0
    degraded_snr_db: float = 6.0


DEFAULT_THRESHOLDS = QualityThresholds()


@dataclass(frozen=True, slots=True)
class QualityAnalysis:
    duration_ms: int
    peak_level_dbfs: float | None
    clipping_detected: bool
    speech_ratio: float
    silence_ratio: float
    estimated_snr_db: float | None
    noise_level: NoiseLevel
    quality_class: AudioQualityLevel


_LEVELS = (
    AudioQualityLevel.GOOD,
    AudioQualityLevel.ACCEPTABLE,
    AudioQualityLevel.DEGRADED,
    AudioQualityLevel.POOR,
    AudioQualityLevel.UNUSABLE,
)


def _downgrade(level: AudioQualityLevel) -> AudioQualityLevel:
    return _LEVELS[min(_LEVELS.index(level) + 1, len(_LEVELS) - 2)]


def detect_clipping(
    samples: npt.NDArray[np.float32],
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """Clipping on the *decoded source* signal, before any normalisation."""
    if samples.size == 0:
        return False
    clipped = int(np.count_nonzero(np.abs(samples) >= thresholds.clip_level))
    return clipped >= max(thresholds.clip_min_samples, thresholds.clip_min_fraction * samples.size)


def analyze_quality(
    samples: npt.NDArray[np.float32],
    sample_rate: int,
    *,
    clipping_detected: bool | None = None,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityAnalysis:
    duration_ms = max(round(samples.size / sample_rate * 1000), 1)

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    peak_dbfs = 20 * np.log10(peak) if peak > _EPSILON else None
    clipping = (
        detect_clipping(samples, thresholds) if clipping_detected is None else clipping_detected
    )

    frame = max(int(sample_rate * thresholds.frame_ms / 1000), 1)
    usable = (samples.size // frame) * frame
    if usable == 0:
        frames = samples.reshape(1, -1) if samples.size else np.zeros((1, 1), dtype=np.float32)
    else:
        frames = samples[:usable].reshape(-1, frame)

    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    levels = 20 * np.log10(rms + _EPSILON)

    noise_floor = float(np.percentile(levels, 10))
    speech_threshold = max(noise_floor + thresholds.speech_margin_db, thresholds.speech_floor_dbfs)
    speech_mask = levels >= speech_threshold

    speech_ratio = float(np.mean(speech_mask))
    silence_ratio = float(np.mean(levels < thresholds.silence_dbfs))

    snr: float | None = None
    if speech_mask.any() and (~speech_mask).any():
        speech_energy = float(np.mean(np.square(rms[speech_mask])))
        snr = 10 * np.log10(speech_energy + _EPSILON) - noise_floor

    if noise_floor < thresholds.noise_low_dbfs:
        noise_level = NoiseLevel.LOW
    elif noise_floor < thresholds.noise_medium_dbfs:
        noise_level = NoiseLevel.MEDIUM
    else:
        noise_level = NoiseLevel.HIGH

    if duration_ms < thresholds.min_duration_ms or speech_ratio < thresholds.unusable_speech_ratio:
        quality = AudioQualityLevel.UNUSABLE
    else:
        if snr is None:
            # Speech everywhere: no noise-floor reference, judge by noise level.
            quality = (
                AudioQualityLevel.ACCEPTABLE
                if noise_level is not NoiseLevel.HIGH
                else AudioQualityLevel.DEGRADED
            )
        elif snr >= thresholds.good_snr_db:
            quality = AudioQualityLevel.GOOD
        elif snr >= thresholds.acceptable_snr_db:
            quality = AudioQualityLevel.ACCEPTABLE
        elif snr >= thresholds.degraded_snr_db:
            quality = AudioQualityLevel.DEGRADED
        else:
            quality = AudioQualityLevel.POOR

        if clipping:
            quality = _downgrade(quality)
        if speech_ratio < thresholds.poor_speech_ratio and quality in _LEVELS[:3]:
            quality = AudioQualityLevel.POOR

    return QualityAnalysis(
        duration_ms=duration_ms,
        peak_level_dbfs=round(float(peak_dbfs), 2) if peak_dbfs is not None else None,
        clipping_detected=clipping,
        speech_ratio=round(speech_ratio, 4),
        silence_ratio=round(silence_ratio, 4),
        estimated_snr_db=round(float(snr), 2) if snr is not None else None,
        noise_level=noise_level,
        quality_class=quality,
    )
