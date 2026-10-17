from io import BytesIO
from uuid import uuid4

import pytest

from vaaniflow.application.ports.asr import (
    ASRProviderError,
    ASRProviderInvalidInputError,
    ASRProviderUnavailableError,
)
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import AudioQualityLevel, NoiseLevel
from vaaniflow.providers.gnani import GnaniASRProvider


class FakeGnaniClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(
            {
                "audio": audio,
                "kwargs": kwargs,
            }
        )

        if self.error is not None:
            raise self.error

        return self.response


def _request(*, language_hint: str | None = "en-IN") -> ASRInput:
    artifact_id = uuid4()

    metadata = AudioMetadata(
        artifact_id=artifact_id,
        mime_type="audio/wav",
        codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        duration_ms=1_000,
        file_size_bytes=3_200,
        noise_level=NoiseLevel.LOW,
        quality_class=AudioQualityLevel.GOOD,
    )

    return ASRInput(
        artifact_id=artifact_id,
        storage_ref="local://audio/test.wav",
        metadata=metadata,
        language_hint=language_hint,
    )


def test_transcribe_maps_gnani_response_to_transcript():
    client = FakeGnaniClient(
        response={
            "success": True,
            "request_id": "gnani-request-123",
            "transcript": "Send 200 bags of cement.",
            "model": "prisma",
            "processing_time": 0.42,
        }
    )

    provider = GnaniASRProvider(client=client)
    request = _request()
    audio = BytesIO(b"fake-audio")

    transcript = provider.transcribe(
        request=request,
        audio=audio,
    )

    assert transcript.provider == "gnani"
    assert transcript.provider_request_id == "gnani-request-123"
    assert transcript.language == "en-IN"
    assert transcript.detected_languages == ["en-IN"]
    assert transcript.text == "Send 200 bags of cement."
    assert transcript.segments == []
    assert transcript.transcript_id != request.artifact_id

    assert len(client.calls) == 1
    assert client.calls[0]["audio"].read() == b"fake-audio"
    assert client.calls[0]["kwargs"] == {
        "language_code": "en-IN",
        "format": "verbatim",
        "itn_native_numerals": False,
    }


def test_transcribe_uses_language_hint():
    client = FakeGnaniClient(
        response={
            "success": True,
            "request_id": "gnani-request-456",
            "transcript": "ನಮಸ್ಕಾರ",
        }
    )

    provider = GnaniASRProvider(client=client)
    request = _request(language_hint="kn-IN")

    transcript = provider.transcribe(
        request=request,
        audio=BytesIO(b"fake-audio"),
    )

    assert transcript.language == "kn-IN"
    assert transcript.detected_languages == ["kn-IN"]
    assert transcript.text == "ನಮಸ್ಕಾರ"

    assert client.calls[0]["kwargs"]["language_code"] == "kn-IN"


def test_transcribe_can_enable_itn_format():
    client = FakeGnaniClient(
        response={
            "success": True,
            "request_id": "gnani-request-789",
            "transcript": "₹420 per bag",
        }
    )

    provider = GnaniASRProvider(
        client=client,
        format="transcribe",
        itn_native_numerals=True,
    )

    provider.transcribe(
        request=_request(),
        audio=BytesIO(b"fake-audio"),
    )

    assert client.calls[0]["kwargs"] == {
        "language_code": "en-IN",
        "format": "transcribe",
        "itn_native_numerals": True,
    }


def test_transcribe_defaults_to_en_in_without_language_hint():
    client = FakeGnaniClient(
        response={
            "success": True,
            "request_id": "gnani-request-default",
            "transcript": "Hello",
        }
    )

    provider = GnaniASRProvider(client=client)
    request = _request(language_hint=None)

    transcript = provider.transcribe(
        request=request,
        audio=BytesIO(b"fake-audio"),
    )

    assert transcript.language == "en-IN"
    assert client.calls[0]["kwargs"]["language_code"] == "en-IN"


def test_invalid_audio_error_maps_to_provider_invalid_input():
    from gnani.stt import InvalidAudioError

    client = FakeGnaniClient(
        error=InvalidAudioError("unsupported audio"),
    )

    provider = GnaniASRProvider(client=client)

    with pytest.raises(
        ASRProviderInvalidInputError,
        match="Gnani rejected the supplied audio input",
    ):
        provider.transcribe(
            request=_request(),
            audio=BytesIO(b"bad-audio"),
        )


def test_authentication_error_maps_to_provider_unavailable():
    from gnani.stt import AuthenticationError

    client = FakeGnaniClient(
        error=AuthenticationError("invalid key"),
    )

    provider = GnaniASRProvider(client=client)

    with pytest.raises(
        ASRProviderUnavailableError,
        match="Gnani authentication failed",
    ):
        provider.transcribe(
            request=_request(),
            audio=BytesIO(b"fake-audio"),
        )


def test_api_error_maps_to_provider_unavailable():
    from gnani.stt import APIError

    client = FakeGnaniClient(
        error=APIError(500, "server error"),
    )

    provider = GnaniASRProvider(client=client)

    with pytest.raises(
        ASRProviderUnavailableError,
        match="Gnani STT API request failed",
    ):
        provider.transcribe(
            request=_request(),
            audio=BytesIO(b"fake-audio"),
        )


def test_malformed_response_maps_to_provider_error():
    client = FakeGnaniClient(
        response={
            "success": True,
            "request_id": "gnani-request-invalid",
        }
    )

    provider = GnaniASRProvider(client=client)

    with pytest.raises(
        ASRProviderError,
        match="did not contain a valid transcript",
    ):
        provider.transcribe(
            request=_request(),
            audio=BytesIO(b"fake-audio"),
        )


def test_non_dict_response_maps_to_provider_error():
    client = FakeGnaniClient(response=None)

    provider = GnaniASRProvider(client=client)

    with pytest.raises(
        ASRProviderError,
        match="invalid response payload",
    ):
        provider.transcribe(
            request=_request(),
            audio=BytesIO(b"fake-audio"),
        )


def test_empty_format_is_rejected():
    client = FakeGnaniClient()

    with pytest.raises(
        ValueError,
        match="Gnani STT format cannot be empty",
    ):
        GnaniASRProvider(
            client=client,
            format="",
        )
