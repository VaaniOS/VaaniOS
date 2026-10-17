from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.schemas.audio_preprocessing import AudioPreprocessingInput
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import AudioProvenance, UnderstandResult
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator


class UnderstandTranscriptService:
    """
    Transcript → SemanticState → InputEvaluation → UnderstandResult.

    This is the UNDERSTAND side's handoff point: the returned
    UnderstandResult is everything the ACT side consumes.
    """

    def __init__(
        self,
        *,
        compiler: SemanticCompiler,
        evaluator: InputEvaluator,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._compiler = compiler
        self._evaluator = evaluator
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        *,
        transcript: Transcript,
        run_id: UUID | None = None,
        audio: AudioProvenance | None = None,
    ) -> UnderstandResult:
        state = self._compiler.compile(transcript, run_id=run_id)
        evaluation = self._evaluator.evaluate(
            state,
            transcript=transcript,
            audio=audio.processed_metadata if audio is not None else None,
        )
        return UnderstandResult(
            result_id=uuid4(),
            run_id=run_id,
            transcript=transcript,
            audio=audio,
            semantic_state=state,
            evaluation=evaluation,
            created_at=self._clock(),
        )


class UnderstandAudioService:
    """
    Stored audio artifact → preprocessing → ASR → UnderstandResult.

    Port errors (ArtifactStorageError, AudioPreprocessorError,
    ASRProviderError) propagate unchanged and typed: a failed stage never
    produces a fabricated transcript or semantic state.
    """

    def __init__(
        self,
        *,
        preprocess_audio: PreprocessAudioService,
        transcribe_audio: TranscribeAudioService,
        understand_transcript: UnderstandTranscriptService,
    ) -> None:
        self._preprocess_audio = preprocess_audio
        self._transcribe_audio = transcribe_audio
        self._understand_transcript = understand_transcript

    def execute(
        self,
        *,
        artifact: AudioArtifact,
        run_id: UUID | None = None,
        language_hint: str | None = None,
    ) -> UnderstandResult:
        processed = self._preprocess_audio.execute(
            request=AudioPreprocessingInput(
                artifact_id=artifact.artifact_id,
                storage_ref=artifact.storage_ref,
                metadata=artifact.metadata,
            )
        )

        transcript = self._transcribe_audio.execute(
            request=ASRInput(
                artifact_id=processed.artifact_id,
                storage_ref=processed.storage_ref,
                metadata=processed.metadata,
                language_hint=language_hint,
            )
        )

        return self._understand_transcript.execute(
            transcript=transcript,
            run_id=run_id,
            audio=AudioProvenance(
                original_artifact_id=artifact.artifact_id,
                processed_artifact_id=processed.artifact_id,
                processed_metadata=processed.metadata,
                applied_operations=processed.applied_operations,
            ),
        )
