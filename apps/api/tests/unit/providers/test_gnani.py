from io import BytesIO
from uuid import uuid4

import pytest

from vaaniflow.application.ports.asr import (
    ASRProviderConfigurationError,
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

    def transcribe_bytes(self, audio_bytes, **kwargs):
        self.calls.append(
            {
                "audio": audio_bytes,
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
    # Gnani does not report language detection; the hint is not "detected".
    assert transcript.detected_languages == []
    assert transcript.text == "Send 200 bags of cement."
    assert transcript.segments == []
    assert transcript.transcript_id != request.artifact_id
    assert transcript.provider_metadata == {
        "format": "verbatim",
        "requested_language": "en-IN",
        "model": "prisma",
        "processing_time": 0.42,
        "end_to_end_latency": None,
    }

    assert len(client.calls) == 1
    assert client.calls[0]["audio"] == b"fake-audio"
    assert client.calls[0]["kwargs"] == {
        "filename": "audio.wav",
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
    assert transcript.detected_languages == []
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
        "filename": "audio.wav",
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


def test_filename_hint_follows_artifact_mime_type():
    client = FakeGnaniClient(response={"success": True, "transcript": "ok"})
    request = _request()
    request = request.model_copy(
        update={"metadata": request.metadata.model_copy(update={"mime_type": "audio/ogg"})}
    )

    GnaniASRProvider(client=client).transcribe(request=request, audio=BytesIO(b"x"))

    assert client.calls[0]["kwargs"]["filename"] == "audio.ogg"


def test_unsuccessful_response_maps_to_provider_error():
    client = FakeGnaniClient(response={"success": False, "transcript": "partial text"})

    with pytest.raises(ASRProviderError, match="unsuccessful"):
        GnaniASRProvider(client=client).transcribe(request=_request(), audio=BytesIO(b"x"))


def test_sdk_configuration_error_maps_to_configuration_error():
    client = FakeGnaniClient(error=ValueError("Unsupported language code 'xx-IN'"))

    with pytest.raises(ASRProviderConfigurationError):
        GnaniASRProvider(client=client).transcribe(
            request=_request(language_hint="xx-IN"), audio=BytesIO(b"x")
        )


def test_network_error_maps_to_provider_unavailable():
    client = FakeGnaniClient(error=ConnectionError("connection reset"))

    with pytest.raises(ASRProviderUnavailableError, match="could not be reached"):
        GnaniASRProvider(client=client).transcribe(request=_request(), audio=BytesIO(b"x"))


def test_non_scalar_provider_metadata_is_dropped():
    client = FakeGnaniClient(
        response={"success": True, "transcript": "ok", "model": {"name": "nested"}}
    )

    transcript = GnaniASRProvider(client=client).transcribe(request=_request(), audio=BytesIO(b"x"))

    assert "model" not in transcript.provider_metadata


def test_from_environment_builds_the_sdk_client_inside_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vaaniflow.providers.gnani as gnani_module

    monkeypatch.setattr(gnani_module, "GnaniSTTClient", FakeGnaniClient)
    provider = GnaniASRProvider.from_environment()
    assert isinstance(provider._client, FakeGnaniClient)
