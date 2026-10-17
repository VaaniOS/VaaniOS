from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest

from vaaniflow.application.ports.artifact_storage import (
    ArtifactNotFoundError,
    ArtifactStorage,
)
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import AudioQualityLevel, NoiseLevel


def make_audio_artifact() -> AudioArtifact:
    return AudioArtifact(
        artifact_id=uuid4(),
        storage_ref="local://audio/test.wav",
        metadata=AudioMetadata(
            artifact_id=uuid4(),
            mime_type="audio/wav",
            codec="pcm_s16le",
            sample_rate_hz=16000,
            channels=1,
            duration_ms=1000,
            file_size_bytes=32000,
            estimated_snr_db=20.0,
            speech_ratio=0.8,
            silence_ratio=0.2,
            peak_level=-1.0,
            clipping_detected=False,
            noise_level=NoiseLevel.LOW,
            quality_class=AudioQualityLevel.GOOD,
        ),
        created_at=datetime.now(UTC),
    )


class InMemoryArtifactStorage:
    """Minimal test implementation of the ArtifactStorage protocol."""

    def __init__(self) -> None:
        self._artifacts: dict[str, bytes] = {}

    def store(
        self,
        *,
        artifact: AudioArtifact,
        data: BytesIO,
    ) -> None:
        self._artifacts[artifact.storage_ref] = data.read()

    def open(
        self,
        *,
        storage_ref: str,
    ) -> BytesIO:
        try:
            data = self._artifacts[storage_ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(storage_ref) from exc

        return BytesIO(data)

    def delete(
        self,
        *,
        storage_ref: str,
    ) -> None:
        try:
            del self._artifacts[storage_ref]
        except KeyError as exc:
            raise ArtifactNotFoundError(storage_ref) from exc


def test_artifact_storage_protocol_can_be_implemented() -> None:
    storage: ArtifactStorage = InMemoryArtifactStorage()
    artifact = make_audio_artifact()
    payload = b"test audio bytes"

    storage.store(
        artifact=artifact,
        data=BytesIO(payload),
    )

    with storage.open(storage_ref=artifact.storage_ref) as stored:
        assert stored.read() == payload


def test_artifact_storage_raises_not_found_for_missing_artifact() -> None:
    storage: ArtifactStorage = InMemoryArtifactStorage()

    with pytest.raises(ArtifactNotFoundError):
        storage.open(storage_ref="local://audio/missing.wav")


def test_artifact_storage_raises_not_found_when_deleting_missing_artifact() -> None:
    storage: ArtifactStorage = InMemoryArtifactStorage()

    with pytest.raises(ArtifactNotFoundError):
        storage.delete(storage_ref="local://audio/missing.wav")


def test_artifact_storage_deletes_artifact() -> None:
    storage: ArtifactStorage = InMemoryArtifactStorage()
    artifact = make_audio_artifact()

    storage.store(
        artifact=artifact,
        data=BytesIO(b"test audio bytes"),
    )

    storage.delete(storage_ref=artifact.storage_ref)

    with pytest.raises(ArtifactNotFoundError):
        storage.open(storage_ref=artifact.storage_ref)
