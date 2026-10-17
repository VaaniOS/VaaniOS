from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.services.transcribe_audio import (
    TranscribeAudioService,
)
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    NoiseLevel,
)
from vaaniflow.domain.schemas.transcript import Transcript


def make_asr_input() -> ASRInput:
    artifact_id = uuid4()

    return ASRInput(
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
        language_hint="en-IN",
    )


class InMemoryArtifactStorage:
    def __init__(self) -> None:
        self._artifacts: dict[str, bytes] = {}

    def store(
        self,
        *,
        storage_ref: str,
        data: bytes,
    ) -> None:
        self._artifacts[storage_ref] = data

    def open(
        self,
        *,
        storage_ref: str,
    ) -> BytesIO:
        return BytesIO(self._artifacts[storage_ref])


class RecordingASR:
    def __init__(self) -> None:
        self.request: ASRInput | None = None
        self.audio_bytes: bytes | None = None

    def transcribe(
        self,
        *,
        request: ASRInput,
        audio: BytesIO,
    ) -> Transcript:
        self.request = request
        self.audio_bytes = audio.read()

        return Transcript(
            transcript_id=uuid4(),
            provider="test-provider",
            provider_request_id=None,
            language=request.language_hint,
            detected_languages=(
                [request.language_hint] if request.language_hint is not None else []
            ),
            text="Send 200 bags of cement",
            segments=[],
            created_at=datetime.now(UTC),
        )


def test_transcribe_audio_retrieves_artifact_and_calls_asr() -> None:
    storage = InMemoryArtifactStorage()
    asr = RecordingASR()

    request = make_asr_input()

    storage.store(
        storage_ref=request.storage_ref,
        data=b"test audio bytes",
    )

    service = TranscribeAudioService(
        artifact_storage=storage,
        asr_provider=asr,
    )

    transcript = service.execute(request=request)

    assert transcript.text == "Send 200 bags of cement"
    assert asr.request == request
    assert asr.audio_bytes == b"test audio bytes"


def test_transcribe_audio_accepts_application_ports() -> None:
    storage = InMemoryArtifactStorage()
    asr = RecordingASR()

    service = TranscribeAudioService(
        artifact_storage=storage,
        asr_provider=asr,
    )

    assert service is not None
