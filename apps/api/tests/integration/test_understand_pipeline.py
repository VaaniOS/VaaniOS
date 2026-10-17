"""
End-to-end UNDERSTAND pipeline:

    stored audio → preprocessing → ASR → Transcript → SemanticState
                 → InputEvaluation → UnderstandResult

Uses the real local storage, real WAV preprocessing/quality analysis, the
real compiler and evaluator, and either MockASR or the Gnani adapter with a
fake SDK client (no network, no credentials).
"""

from __future__ import annotations

import io
import wave
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf

from vaaniflow.application.ports.asr import ASRProviderUnavailableError
from vaaniflow.application.services.ingest_audio import IngestAudioService
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.application.services.understand import (
    UnderstandAudioService,
    UnderstandTranscriptService,
)
from vaaniflow.audio.local import LocalAudioPreprocessor, describe_wav
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.common import Actionability, AudioQualityLevel
from vaaniflow.domain.schemas.semantic import IntentType, RequestedActionType
from vaaniflow.infrastructure.storage.local import LocalArtifactStorage
from vaaniflow.providers.gnani import GnaniASRProvider
from vaaniflow.providers.mock import MockASR
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)


def _voice_note(*, silent: bool = False, rate: int = 8_000, seconds: float = 2.0) -> bytes:
    """Stereo 8 kHz WAV with alternating tone bursts (speech-like energy)."""
    rng = np.random.default_rng(3)
    t = np.arange(int(rate * seconds)) / rate
    if silent:
        mono = np.zeros(t.size, dtype=np.float32)
    else:
        envelope = (np.floor(t / 0.25) % 2 == 0).astype(np.float32)
        mono = 0.5 * np.sin(2 * np.pi * 220 * t) * envelope + rng.normal(0, 0.001, t.size)
    stereo = np.stack([mono, mono], axis=1).astype(np.float32)
    output = io.BytesIO()
    sf.write(output, stereo, rate, format="WAV", subtype="PCM_16")
    return output.getvalue()


def _ingest(storage: LocalArtifactStorage, wav: bytes) -> AudioArtifact:
    artifact_id = uuid4()
    artifact = AudioArtifact(
        artifact_id=artifact_id,
        storage_ref=f"local://original/{artifact_id}.wav",
        metadata=describe_wav(artifact_id=artifact_id, wav_bytes=wav),
        created_at=datetime.now(UTC),
    )
    return IngestAudioService(artifact_storage=storage).execute(
        artifact=artifact, audio=io.BytesIO(wav)
    )


def _pipeline(storage: LocalArtifactStorage, asr: Any) -> UnderstandAudioService:
    return UnderstandAudioService(
        preprocess_audio=PreprocessAudioService(
            artifact_storage=storage, audio_preprocessor=LocalAudioPreprocessor()
        ),
        transcribe_audio=TranscribeAudioService(artifact_storage=storage, asr_provider=asr),
        understand_transcript=UnderstandTranscriptService(
            compiler=SemanticCompiler(), evaluator=InputEvaluator()
        ),
    )


def test_canonical_voice_note_end_to_end_with_mock_asr(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    wav = _voice_note()
    artifact = _ingest(storage, wav)
    run_id = uuid4()

    result = _pipeline(storage, MockASR(text=CANONICAL)).execute(
        artifact=artifact, run_id=run_id, language_hint="hi-IN"
    )

    # Handoff envelope
    assert result.run_id == run_id
    assert result.semantic_state.run_id == run_id
    assert result.actionability is Actionability.PARTIAL
    assert result.transcript.text == CANONICAL
    assert result.transcript.language == "hi-IN"

    # Audio lineage: original preserved, processed stored separately
    assert result.audio is not None
    assert result.audio.original_artifact_id == artifact.artifact_id
    assert result.audio.processed_artifact_id != artifact.artifact_id
    assert result.audio.applied_operations == [
        "decode_wav",
        "downmix_mono",
        "resample_16khz",
        "encode_pcm16",
        "analyze_quality",
    ]
    with storage.open(storage_ref=artifact.storage_ref) as original:
        assert original.read() == wav
    processed_ref = f"local://processed/{result.audio.processed_artifact_id}.wav"
    with storage.open(storage_ref=processed_ref) as processed, wave.open(processed) as reader:
        assert (reader.getframerate(), reader.getnchannels()) == (16_000, 1)

    # Measured quality metadata
    metadata = result.audio.processed_metadata
    assert metadata.quality_class is AudioQualityLevel.GOOD
    assert metadata.sample_rate_hz == 16_000

    # Semantic content
    state = result.semantic_state
    assert state.source_transcript_id == result.transcript.transcript_id
    assert state.intent is IntentType.CREATE_DISPATCH_ORDER
    assert state.customer is not None and state.customer.surface_text == "Sharma Builders"
    assert [
        (i.product.surface_text if i.product else None, i.quantity.value if i.quantity else None)
        for i in state.items
    ] == [("Ultratech cement", Decimal(200))]
    assert state.pricing[0].amount == Decimal(420)
    assert [a.action_type for a in state.requested_actions] == [
        RequestedActionType.DISPATCH,
        RequestedActionType.CREATE_INVOICE_DRAFT,
        RequestedActionType.SEND_NOTIFICATION,
        RequestedActionType.REQUEST_APPROVAL,
    ]


class _FakeGnaniClient:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.calls: list[dict[str, Any]] = []

    def transcribe_bytes(self, audio_bytes: bytes, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"audio": audio_bytes, **kwargs})
        return {"success": True, "request_id": "req-1", "transcript": self.transcript}


def test_pipeline_with_gnani_adapter_sends_the_processed_audio(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    client = _FakeGnaniClient(CANONICAL)
    artifact = _ingest(storage, _voice_note())

    provider = GnaniASRProvider(client=client)  # type: ignore[arg-type]  # SDK client stand-in
    result = _pipeline(storage, provider).execute(artifact=artifact, language_hint="hi-IN")

    call = client.calls[0]
    assert call["filename"] == "audio.wav"
    assert call["language_code"] == "hi-IN"
    with wave.open(io.BytesIO(call["audio"])) as reader:
        assert reader.getframerate() == 16_000  # processed, not original 8 kHz
    assert result.transcript.provider == "gnani"
    assert result.transcript.provider_request_id == "req-1"
    assert result.transcript.detected_languages == []
    assert result.actionability is Actionability.PARTIAL


def test_asr_failure_propagates_typed_and_produces_no_result(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    artifact = _ingest(storage, _voice_note())

    class _DownASR:
        def transcribe(self, *, request: Any, audio: Any) -> Any:
            raise ASRProviderUnavailableError("provider down")

    with pytest.raises(ASRProviderUnavailableError):
        _pipeline(storage, _DownASR()).execute(artifact=artifact)


def test_silent_recording_is_blocked_by_input_evaluation(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    artifact = _ingest(storage, _voice_note(silent=True))

    result = _pipeline(storage, MockASR(text=CANONICAL)).execute(artifact=artifact)

    assert result.audio is not None
    assert result.audio.processed_metadata.quality_class is AudioQualityLevel.UNUSABLE
    assert result.actionability is Actionability.BLOCKED
    assert result.evaluation.reasons[0].code.value == "UNUSABLE_AUDIO"


def test_reprocessing_the_same_artifact_keeps_both_processed_versions(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    artifact = _ingest(storage, _voice_note())
    pipeline = _pipeline(storage, MockASR(text=CANONICAL))

    first = pipeline.execute(artifact=artifact)
    second = pipeline.execute(artifact=artifact)

    assert first.audio is not None and second.audio is not None
    assert first.audio.processed_artifact_id != second.audio.processed_artifact_id
    assert len(list((tmp_path / "processed").iterdir())) == 2


@pytest.mark.parametrize(
    ("text", "actionability"),
    [
        ("Sharma Builders ko 200 bags UltraTech cement dispatch karo.", Actionability.COMPLETE),
        ("Dispatch 200 bags UltraTech cement.", Actionability.CLARIFICATION_REQUIRED),
        ("Hello, how are you?", Actionability.BLOCKED),
    ],
)
def test_transcript_only_entry_point(text: str, actionability: Actionability) -> None:
    from vaaniflow.domain.schemas.transcript import Transcript

    transcript = Transcript(
        transcript_id=uuid4(), provider="mock", text=text, created_at=datetime.now(UTC)
    )
    result = UnderstandTranscriptService(
        compiler=SemanticCompiler(), evaluator=InputEvaluator()
    ).execute(transcript=transcript)

    assert result.audio is None
    assert result.actionability is actionability
