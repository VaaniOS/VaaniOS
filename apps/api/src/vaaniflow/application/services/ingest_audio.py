from __future__ import annotations

from io import BufferedIOBase

from vaaniflow.application.ports.artifact_storage import ArtifactStorage
from vaaniflow.domain.schemas.artifact import AudioArtifact


class IngestAudioService:
    """
    Application service responsible for persisting an audio artifact.

    The service depends only on the ArtifactStorage application port.
    It does not know whether the artifact is stored on the local
    filesystem, object storage, or another backend.
    """

    def __init__(self, *, artifact_storage: ArtifactStorage) -> None:
        self._artifact_storage = artifact_storage

    def execute(
        self,
        *,
        artifact: AudioArtifact,
        audio: BufferedIOBase,
    ) -> AudioArtifact:
        """
        Persist an audio artifact and return the canonical artifact.

        The artifact metadata is supplied by the caller after audio
        processing/analysis. The storage implementation owns the
        physical representation of the audio bytes.
        """
        self._artifact_storage.store(
            artifact=artifact,
            data=audio,
        )

        return artifact
