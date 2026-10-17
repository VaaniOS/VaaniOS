from __future__ import annotations

from vaaniflow.application.ports.artifact_storage import ArtifactStorage
from vaaniflow.application.ports.audio_preprocessor import AudioPreprocessor
from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
    AudioPreprocessingResult,
)


class PreprocessAudioService:
    """
    Application service coordinating audio retrieval, preprocessing,
    and persistence of the resulting audio artifact.

    The service depends only on application ports. It does not know
    which storage backend or preprocessing implementation is used.
    """

    def __init__(
        self,
        *,
        artifact_storage: ArtifactStorage,
        audio_preprocessor: AudioPreprocessor,
    ) -> None:
        self._artifact_storage = artifact_storage
        self._audio_preprocessor = audio_preprocessor

    def execute(
        self,
        *,
        request: AudioPreprocessingInput,
    ) -> AudioPreprocessingResult:
        """
        Retrieve the source artifact, preprocess it, persist the
        resulting artifact, and return its canonical metadata.
        """
        with self._artifact_storage.open(
            storage_ref=request.storage_ref,
        ) as audio:
            result, processed_audio = self._audio_preprocessor.preprocess(
                request=request,
                audio=audio,
            )

        with processed_audio:
            self._artifact_storage.store(
                artifact=_result_to_artifact(result),
                data=processed_audio,
            )

        return result


def _result_to_artifact(
    result: AudioPreprocessingResult,
):
    """
    Convert the preprocessing result into the domain artifact expected
    by the storage port.

    The resulting artifact uses the preprocessing result's identity,
    storage reference, and metadata.
    """
    from datetime import UTC, datetime

    from vaaniflow.domain.schemas.artifact import AudioArtifact

    return AudioArtifact(
        artifact_id=result.artifact_id,
        storage_ref=result.storage_ref,
        metadata=result.metadata,
        created_at=datetime.now(UTC),
    )
