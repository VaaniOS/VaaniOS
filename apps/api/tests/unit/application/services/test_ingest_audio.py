from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from vaaniflow.application.services.ingest_audio import IngestAudioService
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    NoiseLevel,
)


def make_audio_artifact() -> AudioArtifact:
    artifact_id = uuid4()

    return AudioArtifact(
        artifact_id=artifact_id,
        storage_ref="local://audio/test.wav",
        metadata=AudioMetadata(
            artifact_id=artifact_id,
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


class RecordingArtifactStorage:
    def __init__(self) -> None:
        self.artifact: AudioArtifact | None = None
        self.audio_bytes: bytes | None = None

    def store(
        self,
        *,
        artifact: AudioArtifact,
        data: BytesIO,
    ) -> None:
        self.artifact = artifact
        self.audio_bytes = data.read()

    def open(self, *, storage_ref: str) -> BytesIO:
        raise NotImplementedError

    def delete(self, *, storage_ref: str) -> None:
        raise NotImplementedError


def test_ingest_audio_stores_artifact_and_audio() -> None:
    storage = RecordingArtifactStorage()
    service = IngestAudioService(
        artifact_storage=storage,
    )

    artifact = make_audio_artifact()
    audio = BytesIO(b"test audio bytes")

    result = service.execute(
        artifact=artifact,
        audio=audio,
    )

    assert result == artifact
    assert storage.artifact == artifact
    assert storage.audio_bytes == b"test audio bytes"


def test_ingest_audio_returns_same_artifact_after_storage() -> None:
    storage = RecordingArtifactStorage()
    service = IngestAudioService(
        artifact_storage=storage,
    )

    artifact = make_audio_artifact()

    result = service.execute(
        artifact=artifact,
        audio=BytesIO(b"audio"),
    )

    assert result is artifact
