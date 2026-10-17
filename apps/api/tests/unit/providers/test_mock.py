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
from vaaniflow.providers.mock import MockASR


def make_asr_input(
    language_hint: str | None = "en-IN",
) -> ASRInput:
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
        language_hint=language_hint,
    )


def test_mock_asr_implements_asr_provider() -> None:
    provider: ASRProvider = MockASR()

    transcript = provider.transcribe(
        request=make_asr_input(),
        audio=BytesIO(b"test audio bytes"),
    )

    assert isinstance(transcript, Transcript)


def test_mock_asr_returns_deterministic_transcript() -> None:
    provider = MockASR(
        text="Send 200 bags of cement",
    )

    transcript = provider.transcribe(
        request=make_asr_input(),
        audio=BytesIO(b"test audio bytes"),
    )

    assert transcript.provider == "mock"
    assert transcript.text == "Send 200 bags of cement"
    assert transcript.language == "en-IN"
    # The mock performs no language identification.
    assert transcript.detected_languages == []
    assert transcript.segments == []


def test_mock_asr_uses_custom_provider_name() -> None:
    provider = MockASR(
        provider="test-provider",
    )

    transcript = provider.transcribe(
        request=make_asr_input(),
        audio=BytesIO(b"test audio bytes"),
    )

    assert transcript.provider == "test-provider"


def test_mock_asr_handles_missing_language_hint() -> None:
    provider = MockASR()

    transcript = provider.transcribe(
        request=make_asr_input(language_hint=None),
        audio=BytesIO(b"test audio bytes"),
    )

    assert transcript.language is None
    assert transcript.detected_languages == []


def test_mock_asr_consumes_audio_stream() -> None:
    provider = MockASR()

    audio = BytesIO(b"test audio bytes")

    provider.transcribe(
        request=make_asr_input(),
        audio=audio,
    )

    assert audio.tell() == len(b"test audio bytes")


def test_mock_asr_generates_transcript_timestamp() -> None:
    provider = MockASR()

    before = datetime.now(UTC)

    transcript = provider.transcribe(
        request=make_asr_input(),
        audio=BytesIO(b"test audio bytes"),
    )

    after = datetime.now(UTC)

    assert before <= transcript.created_at <= after


def test_mock_asr_rejects_empty_text() -> None:
    try:
        MockASR(text="")
    except ValueError as exc:
        assert str(exc) == "Mock ASR text cannot be empty."
    else:
        raise AssertionError("Expected ValueError")


def test_mock_asr_rejects_empty_provider_name() -> None:
    try:
        MockASR(provider="")
    except ValueError as exc:
        assert str(exc) == "Mock ASR provider name cannot be empty."
    else:
        raise AssertionError("Expected ValueError")
