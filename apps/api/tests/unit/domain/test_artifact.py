from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import AudioQualityLevel, NoiseLevel


def make_audio_metadata() -> AudioMetadata:
    return AudioMetadata(
        artifact_id=uuid4(),
        mime_type="audio/wav",
        codec="pcm_s16le",
        sample_rate_hz=16000,
        channels=1,
        duration_ms=5000,
        file_size_bytes=160000,
        estimated_snr_db=24.5,
        speech_ratio=0.72,
        silence_ratio=0.28,
        peak_level=-1.2,
        clipping_detected=False,
        noise_level=NoiseLevel.LOW,
        quality_class=AudioQualityLevel.GOOD,
    )


def test_audio_artifact_accepts_valid_metadata() -> None:
    artifact_id = uuid4()

    artifact = AudioArtifact(
        artifact_id=artifact_id,
        storage_ref="local://audio/original.wav",
        metadata=make_audio_metadata(),
        created_at=datetime.now(UTC),
    )

    assert artifact.artifact_id == artifact_id
    assert artifact.storage_ref == "local://audio/original.wav"
    assert artifact.metadata.mime_type == "audio/wav"


def test_audio_artifact_rejects_empty_storage_reference() -> None:
    with pytest.raises(ValidationError):
        AudioArtifact(
            artifact_id=uuid4(),
            storage_ref="",
            metadata=make_audio_metadata(),
            created_at=datetime.now(UTC),
        )


def test_audio_artifact_rejects_invalid_metadata() -> None:
    with pytest.raises(ValidationError):
        AudioArtifact(
            artifact_id=uuid4(),
            storage_ref="local://audio/original.wav",
            metadata={
                "artifact_id": uuid4(),
                "mime_type": "audio/wav",
                "sample_rate_hz": 0,
                "channels": 1,
                "duration_ms": 5000,
                "file_size_bytes": 160000,
                "noise_level": "LOW",
                "quality_class": "GOOD",
            },
            created_at=datetime.now(UTC),
        )
