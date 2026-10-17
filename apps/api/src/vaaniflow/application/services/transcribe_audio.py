from __future__ import annotations

from vaaniflow.application.ports.artifact_storage import ArtifactStorage
from vaaniflow.application.ports.asr import ASRProvider
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.transcript import Transcript


class TranscribeAudioService:
    """
    Application service coordinating artifact retrieval and ASR.

    The service depends only on application ports. It does not know
    which storage backend or ASR provider is being used.
    """

    def __init__(
        self,
        *,
        artifact_storage: ArtifactStorage,
        asr_provider: ASRProvider,
    ) -> None:
        self._artifact_storage = artifact_storage
        self._asr_provider = asr_provider

    def execute(
        self,
        *,
        request: ASRInput,
    ) -> Transcript:
        """
        Retrieve the referenced audio artifact and transcribe it.
        """

        with self._artifact_storage.open(
            storage_ref=request.storage_ref,
        ) as audio:
            return self._asr_provider.transcribe(
                request=request,
                audio=audio,
            )