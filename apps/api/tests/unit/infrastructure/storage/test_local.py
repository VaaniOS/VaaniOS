from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from vaaniflow.application.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactStorage,
    ArtifactStorageError,
)
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    NoiseLevel,
)
from vaaniflow.infrastructure.storage.local import LocalArtifactStorage


def make_audio_artifact(
    storage_ref: str = "local://audio/test.wav",
) -> AudioArtifact:
    artifact_id = uuid4()

    return AudioArtifact(
        artifact_id=artifact_id,
        storage_ref=storage_ref,
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


def test_local_storage_implements_artifact_storage(
    tmp_path: Path,
) -> None:
    storage: ArtifactStorage = LocalArtifactStorage(tmp_path)

    artifact = make_audio_artifact()

    storage.store(
        artifact=artifact,
        data=BytesIO(b"test audio bytes"),
    )

    with storage.open(storage_ref=artifact.storage_ref) as stored:
        assert stored.read() == b"test audio bytes"


def test_local_storage_creates_parent_directories(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    artifact = make_audio_artifact(
        storage_ref="local://audio/nested/test.wav",
    )

    storage.store(
        artifact=artifact,
        data=BytesIO(b"audio"),
    )

    expected_path = tmp_path / "audio" / "nested" / "test.wav"

    assert expected_path.is_file()
    assert expected_path.read_bytes() == b"audio"


def test_local_storage_refuses_to_overwrite_existing_artifact(
    tmp_path: Path,
) -> None:
    """Artifacts are write-once: original audio evidence is never replaced."""
    storage = LocalArtifactStorage(tmp_path)

    artifact = make_audio_artifact()

    storage.store(
        artifact=artifact,
        data=BytesIO(b"first payload"),
    )

    with pytest.raises(ArtifactAlreadyExistsError):
        storage.store(
            artifact=artifact,
            data=BytesIO(b"second payload"),
        )

    with storage.open(storage_ref=artifact.storage_ref) as stored:
        assert stored.read() == b"first payload"


def test_local_storage_raises_not_found_for_missing_artifact(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ArtifactNotFoundError):
        storage.open(
            storage_ref="local://audio/missing.wav",
        )


def test_local_storage_raises_not_found_when_deleting_missing_artifact(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ArtifactNotFoundError):
        storage.delete(
            storage_ref="local://audio/missing.wav",
        )


def test_local_storage_deletes_artifact(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    artifact = make_audio_artifact()

    storage.store(
        artifact=artifact,
        data=BytesIO(b"test audio bytes"),
    )

    storage.delete(
        storage_ref=artifact.storage_ref,
    )

    with pytest.raises(ArtifactNotFoundError):
        storage.open(
            storage_ref=artifact.storage_ref,
        )


def test_local_storage_rejects_unsupported_scheme(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ArtifactStorageError):
        storage.open(
            storage_ref="s3://audio/test.wav",
        )


def test_local_storage_rejects_path_traversal(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ArtifactStorageError):
        storage.open(
            storage_ref="local://../outside.wav",
        )


def test_local_storage_rejects_empty_reference(
    tmp_path: Path,
) -> None:
    storage = LocalArtifactStorage(tmp_path)

    with pytest.raises(ArtifactStorageError):
        storage.open(
            storage_ref="local://",
        )
