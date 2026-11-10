"""
Voice intake for adapters that receive raw audio (Telegram voice notes).

    raw audio → (caller converts to 16 kHz mono PCM16 WAV) → ingest (write-once
    original) → preprocess (measured quality) → ASR provider → Transcript

The Transcript then goes through the same UNDERSTAND/ACT pipeline as typed text
(``VoiceWorkflowOrchestrator.process_transcript``). Nothing is substituted: if
any stage fails, or the provider returns no usable text, a VoiceIntakeError is
raised and no instruction is processed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from vaaniflow.application.ports.artifact_storage import ArtifactStorage, ArtifactStorageError
from vaaniflow.application.ports.asr import (
    ASRProvider,
    ASRProviderConfigurationError,
    ASRProviderError,
    ASRProviderInvalidInputError,
    ASRProviderUnavailableError,
)
from vaaniflow.application.ports.audio_preprocessor import (
    AudioPreprocessor,
    AudioPreprocessorError,
)
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.schemas.audio_preprocessing import AudioPreprocessingInput
from vaaniflow.application.services.ingest_audio import IngestAudioService
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.audio import describe_wav
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.transcript import Transcript


class VoiceIntakeError(Exception):
    """A voice note could not become a transcript. ``message`` is safe to show users."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VoiceTranscript:
    """The provider's transcript and the measured quality of the processed audio."""

    transcript: Transcript
    audio: AudioMetadata


class VoiceIntakeService:
    def __init__(
        self,
        *,
        artifact_storage: ArtifactStorage,
        audio_preprocessor: AudioPreprocessor,
        asr_provider: ASRProvider,
        language_hint: str | None = None,
    ) -> None:
        self._ingest = IngestAudioService(artifact_storage=artifact_storage)
        self._preprocess = PreprocessAudioService(
            artifact_storage=artifact_storage, audio_preprocessor=audio_preprocessor
        )
        self._transcribe = TranscribeAudioService(
            artifact_storage=artifact_storage, asr_provider=asr_provider
        )
        self._language_hint = language_hint

    def transcribe_wav(self, wav: bytes, *, now: datetime) -> VoiceTranscript:
        """Transcribe canonical WAV bytes; raise VoiceIntakeError on any failure."""
        artifact_id = uuid4()
        try:
            metadata = describe_wav(artifact_id=artifact_id, wav_bytes=wav)
            artifact = self._ingest.execute(
                artifact=AudioArtifact(
                    artifact_id=artifact_id,
                    storage_ref=f"local://original/{artifact_id}.wav",
                    metadata=metadata,
                    created_at=now,
                ),
                audio=io.BytesIO(wav),
            )
            processed = self._preprocess.execute(
                request=AudioPreprocessingInput(
                    artifact_id=artifact.artifact_id,
                    storage_ref=artifact.storage_ref,
                    metadata=artifact.metadata,
                )
            )
        except (AudioPreprocessorError, ValueError, RuntimeError) as exc:
            raise VoiceIntakeError(
                "INVALID_AUDIO", f"The voice note could not be read ({type(exc).__name__})."
            ) from exc
        except ArtifactStorageError as exc:
            raise VoiceIntakeError("STORAGE_FAILED", "The voice note could not be stored.") from exc

        try:
            transcript = self._transcribe.execute(
                request=ASRInput(
                    artifact_id=processed.artifact_id,
                    storage_ref=processed.storage_ref,
                    metadata=processed.metadata,
                    language_hint=self._language_hint,
                )
            )
        except ASRProviderInvalidInputError as exc:
            raise VoiceIntakeError(
                "ASR_REJECTED_AUDIO", "The speech service could not use this audio."
            ) from exc
        except (ASRProviderUnavailableError, ASRProviderConfigurationError) as exc:
            raise VoiceIntakeError(
                "ASR_UNAVAILABLE", "The speech service is unavailable right now."
            ) from exc
        except ASRProviderError as exc:
            raise VoiceIntakeError(
                "ASR_FAILED", "The speech service could not transcribe this voice note."
            ) from exc
        except ArtifactStorageError as exc:
            raise VoiceIntakeError("STORAGE_FAILED", "The voice note could not be stored.") from exc

        if not transcript.text.strip():
            raise VoiceIntakeError(
                "EMPTY_TRANSCRIPT", "No speech was recognised in the voice note."
            )
        return VoiceTranscript(transcript=transcript, audio=processed.metadata)
