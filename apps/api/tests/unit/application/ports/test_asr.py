from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

from vaaniflow.application.ports.asr import ASRProvider
from vaaniflow.application.schemas.asr import ASRInput
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


class MockASR:
    """Minimal test implementation of the ASRProvider protocol."""

    def transcribe(
        self,
        *,
        request: ASRInput,
        audio: BytesIO,
    ) -> Transcript:
        assert request.language_hint == "en-IN"
        assert request.storage_ref == "local://audio/test.wav"
        assert audio.read() == b"test audio bytes"

        return Transcript(
            transcript_id=uuid4(),
            provider="mock",
            provider_request_id=None,
            language="en-IN",
            detected_languages=["en-IN"],
            text="Test transcription",
            segments=[],
            created_at=datetime.now(UTC),
        )


def test_asr_provider_protocol_can_be_implemented() -> None:
    provider: ASRProvider = MockASR()

    transcript = provider.transcribe(
        request=make_asr_input(),
        audio=BytesIO(b"test audio bytes"),
    )

    assert isinstance(transcript, Transcript)
    assert transcript.provider == "mock"
    assert transcript.text == "Test transcription"
