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

    assert result.storage_ref == "local://processed/audio/input.wav"
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


def test_local_preprocessor_preserves_source_quality_metadata() -> None:
    request = make_request()

    preprocessor = LocalAudioPreprocessor()

    result, _ = preprocessor.preprocess(
        request=request,
        audio=io.BytesIO(
            make_wav(
                sample_rate=8000,
                channels=1,
                frames=800,
            )
        ),
    )

    assert result.metadata.noise_level == request.metadata.noise_level
    assert result.metadata.quality_class == request.metadata.quality_class
    assert result.metadata.estimated_snr_db == request.metadata.estimated_snr_db
    assert result.metadata.speech_ratio == request.metadata.speech_ratio
    assert result.metadata.silence_ratio == request.metadata.silence_ratio
    assert result.metadata.peak_level == request.metadata.peak_level
    assert result.metadata.clipping_detected == request.metadata.clipping_detected
