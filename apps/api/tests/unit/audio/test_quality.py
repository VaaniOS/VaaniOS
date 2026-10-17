from __future__ import annotations

import numpy as np

from vaaniflow.audio.quality import analyze_quality, detect_clipping
from vaaniflow.domain.schemas.common import AudioQualityLevel, NoiseLevel

RATE = 16_000


def _speech_like(*, noise: float, seconds: float = 2.0, seed: int = 7) -> np.ndarray:
    """Alternating 250 ms tone bursts and pauses over a noise floor."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(RATE * seconds)) / RATE
    envelope = (np.floor(t / 0.25) % 2 == 0).astype(np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 220 * t) * envelope
    return (tone + rng.normal(0, noise, t.size)).astype(np.float32)


def test_clean_speech_like_signal_is_good() -> None:
    analysis = analyze_quality(_speech_like(noise=0.001), RATE)

    assert analysis.quality_class is AudioQualityLevel.GOOD
    assert analysis.noise_level is NoiseLevel.LOW
    assert 0.4 <= analysis.speech_ratio <= 0.6
    assert analysis.estimated_snr_db is not None and analysis.estimated_snr_db > 20
    assert analysis.clipping_detected is False


def test_noisy_signal_is_degraded_or_worse() -> None:
    analysis = analyze_quality(_speech_like(noise=0.12), RATE)

    assert analysis.quality_class in (AudioQualityLevel.DEGRADED, AudioQualityLevel.POOR)
    assert analysis.noise_level is NoiseLevel.HIGH


def test_silence_is_unusable() -> None:
    analysis = analyze_quality(np.zeros(RATE, dtype=np.float32), RATE)

    assert analysis.quality_class is AudioQualityLevel.UNUSABLE
    assert analysis.speech_ratio == 0.0
    assert analysis.peak_level_dbfs is None


def test_very_short_audio_is_unusable() -> None:
    analysis = analyze_quality(_speech_like(noise=0.001, seconds=0.1), RATE)

    assert analysis.quality_class is AudioQualityLevel.UNUSABLE


def test_clipping_downgrades_quality() -> None:
    clean = _speech_like(noise=0.001)
    clipped = analyze_quality(clean, RATE, clipping_detected=True)

    assert clipped.clipping_detected is True
    assert clipped.quality_class is AudioQualityLevel.ACCEPTABLE


def test_detect_clipping_requires_more_than_isolated_peaks() -> None:
    samples = np.zeros(RATE, dtype=np.float32)
    samples[100] = 1.0

    assert detect_clipping(samples) is False

    samples[:50] = 1.0
    assert detect_clipping(samples) is True
