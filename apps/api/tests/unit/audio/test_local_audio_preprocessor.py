from __future__ import annotations

import io
import wave
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf

from vaaniflow.application.ports.audio_preprocessor import (
    AudioPreprocessorInvalidInputError,
)
from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
)
from vaaniflow.audio.local import LocalAudioPreprocessor
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    NoiseLevel,
)


def make_wav(
    *,
    sample_rate: int = 8000,
    channels: int = 2,
    frames: int = 800,
) -> bytes:
    output = io.BytesIO()

    samples = np.zeros(
        (frames, channels),
        dtype=np.float32,
    )

    sf.write(
        output,
        samples,
        sample_rate,
        format="WAV",
        subtype="PCM_16",
    )

    return output.getvalue()


def make_request() -> AudioPreprocessingInput:
    artifact_id = uuid4()

    return AudioPreprocessingInput(
        artifact_id=artifact_id,
        storage_ref="local://audio/input.wav",
        metadata=AudioMetadata(
            artifact_id=artifact_id,
            mime_type="audio/wav",
            codec="pcm_s16le",
            sample_rate_hz=8000,
            channels=2,
            duration_ms=100,
            file_size_bytes=2000,
            estimated_snr_db=10.0,
            speech_ratio=0.7,
            silence_ratio=0.3,
            peak_level=-3.0,
            clipping_detected=False,
            noise_level=NoiseLevel.MEDIUM,
            quality_class=AudioQualityLevel.ACCEPTABLE,
        ),
    )


def test_local_preprocessor_normalizes_wav() -> None:
    preprocessor = LocalAudioPreprocessor()

    result, processed = preprocessor.preprocess(
        request=make_request(),
        audio=io.BytesIO(
            make_wav(
                sample_rate=8000,
                channels=2,
                frames=800,
            )
        ),
    )

    with wave.open(processed, "rb") as reader:
        assert reader.getframerate() == 16_000
        assert reader.getnchannels() == 1
        assert reader.getsampwidth() == 2

    # Unique, write-once location keyed by the new artifact id.
    assert result.storage_ref == f"local://processed/{result.artifact_id}.wav"
    assert result.metadata.sample_rate_hz == 16_000
    assert result.metadata.channels == 1
    assert result.metadata.codec == "pcm_s16le"
    assert result.metadata.artifact_id == result.artifact_id


def test_local_preprocessor_rejects_empty_audio() -> None:
    preprocessor = LocalAudioPreprocessor()

    with pytest.raises(AudioPreprocessorInvalidInputError):
        preprocessor.preprocess(
            request=make_request(),
            audio=io.BytesIO(),
        )


def test_local_preprocessor_rejects_invalid_audio() -> None:
    preprocessor = LocalAudioPreprocessor()

    with pytest.raises(AudioPreprocessorInvalidInputError):
        preprocessor.preprocess(
            request=make_request(),
            audio=io.BytesIO(b"not a wav file"),
        )


def test_local_preprocessor_records_lineage_and_operations() -> None:
    request = make_request()

    result, _ = LocalAudioPreprocessor().preprocess(
        request=request,
        audio=io.BytesIO(make_wav(sample_rate=8000, channels=2, frames=800)),
    )

    assert result.source_artifact_id == request.artifact_id
    assert result.artifact_id != request.artifact_id
    assert result.applied_operations == [
        "decode_wav",
        "downmix_mono",
        "resample_16khz",
        "encode_pcm16",
        "analyze_quality",
    ]


def test_local_preprocessor_skips_operations_that_are_not_needed() -> None:
    result, _ = LocalAudioPreprocessor().preprocess(
        request=make_request(),
        audio=io.BytesIO(make_wav(sample_rate=16_000, channels=1, frames=1600)),
    )

    assert result.applied_operations == ["decode_wav", "encode_pcm16", "analyze_quality"]


def test_local_preprocessor_reprocessing_never_reuses_a_storage_ref() -> None:
    preprocessor = LocalAudioPreprocessor()
    request = make_request()

    first, _ = preprocessor.preprocess(request=request, audio=io.BytesIO(make_wav()))
    second, _ = preprocessor.preprocess(request=request, audio=io.BytesIO(make_wav()))

    assert first.storage_ref != second.storage_ref


def test_local_preprocessor_measures_quality_instead_of_copying_caller_metadata() -> None:
    """The caller claims ACCEPTABLE audio; the processed signal is digital silence."""
    request = make_request()

    result, _ = LocalAudioPreprocessor().preprocess(
        request=request,
        audio=io.BytesIO(make_wav(sample_rate=8000, channels=1, frames=8000)),
    )

    assert request.metadata.quality_class is AudioQualityLevel.ACCEPTABLE
    assert result.metadata.quality_class is AudioQualityLevel.UNUSABLE
    assert result.metadata.speech_ratio == 0.0
    assert result.metadata.silence_ratio == 1.0
    assert result.metadata.peak_level is None
    assert result.metadata.estimated_snr_db is None
    assert result.metadata.noise_level is NoiseLevel.LOW


def test_local_preprocessor_detects_clipping_in_the_source_signal() -> None:
    output = io.BytesIO()
    samples = np.full(16_000, 1.0, dtype=np.float32)
    samples[::2] = -1.0
    sf.write(output, samples, 16_000, format="WAV", subtype="PCM_16")

    result, _ = LocalAudioPreprocessor().preprocess(
        request=make_request(),
        audio=io.BytesIO(output.getvalue()),
    )

    assert result.metadata.clipping_detected is True
