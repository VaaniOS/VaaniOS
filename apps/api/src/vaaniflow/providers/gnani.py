from __future__ import annotations

from datetime import UTC, datetime
from io import BufferedIOBase
from uuid import uuid4

from gnani.stt import (
    APIError,
    AuthenticationError,
    GnaniSTTClient,
    InvalidAudioError,
)

from vaaniflow.application.ports.asr import (
    ASRProvider,
    ASRProviderConfigurationError,
    ASRProviderError,
    ASRProviderInvalidInputError,
    ASRProviderUnavailableError,
)
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.transcript import Transcript

# Filename hints let the Gnani REST endpoint infer the container format
# (``GnaniSTTClient.transcribe_bytes``). Extensions are those the SDK lists
# as supported.
_FILENAME_BY_MIME = {
    "audio/wav": "audio.wav",
    "audio/x-wav": "audio.wav",
    "audio/wave": "audio.wav",
    "audio/mpeg": "audio.mp3",
    "audio/mp3": "audio.mp3",
    "audio/flac": "audio.flac",
    "audio/ogg": "audio.ogg",
    "audio/opus": "audio.ogg",
    "audio/mp4": "audio.m4a",
    "audio/m4a": "audio.m4a",
    "audio/x-m4a": "audio.m4a",
    "audio/aac": "audio.aac",
}

# Response fields kept as opaque provider diagnostics. The SDK documents
# ``model``, ``processing_time`` and ``end_to_end_latency`` as metadata.
_METADATA_FIELDS = ("model", "processing_time", "end_to_end_latency")


class GnaniASRProvider:
    """
    Gnani Vachana Speech-to-Text adapter (``gnani-vachana`` SDK).

    This adapter isolates the Gnani SDK from the VaaniFlow application
    and domain layers. Gnani-specific response payloads and exceptions
    are translated into provider-neutral VaaniFlow contracts.

    The REST response carries no detected-language information, so
    ``Transcript.detected_languages`` is left empty rather than echoing the
    requested language as if it had been detected.
    """

    DEFAULT_LANGUAGE = "en-IN"
    DEFAULT_FORMAT = "verbatim"

    def __init__(
        self,
        *,
        client: GnaniSTTClient,
        format: str = DEFAULT_FORMAT,
        itn_native_numerals: bool = False,
    ) -> None:
        if not format:
            raise ValueError("Gnani STT format cannot be empty.")

        self._client = client
        self._format = format
        self._itn_native_numerals = itn_native_numerals

    @classmethod
    def from_environment(
        cls,
        *,
        format: str = DEFAULT_FORMAT,
        itn_native_numerals: bool = False,
    ) -> GnaniASRProvider:
        """
        Build the adapter with an SDK client configured from the environment
        (``GNANI_API_KEY``, read by ``GnaniSTTClient``). Callers outside this
        module never construct or import the Gnani SDK.
        """
        return cls(client=GnaniSTTClient(), format=format, itn_native_numerals=itn_native_numerals)

    def transcribe(
        self,
        *,
        request: ASRInput,
        audio: BufferedIOBase,
    ) -> Transcript:
        """
        Transcribe audio through Gnani and return a VaaniFlow Transcript.

        Provider-specific response fields are translated into the
        provider-neutral Transcript domain model.
        """
        language_code = request.language_hint or self.DEFAULT_LANGUAGE
        audio_bytes = audio.read()
        filename = _FILENAME_BY_MIME.get(request.metadata.mime_type.casefold(), "audio.wav")

        try:
            response = self._client.transcribe_bytes(
                audio_bytes,
                filename=filename,
                language_code=language_code,
                format=self._format,
                itn_native_numerals=self._itn_native_numerals,
            )
        except InvalidAudioError as exc:
            raise ASRProviderInvalidInputError("Gnani rejected the supplied audio input.") from exc
        except AuthenticationError as exc:
            raise ASRProviderUnavailableError("Gnani authentication failed.") from exc
        except APIError as exc:
            raise ASRProviderUnavailableError("Gnani STT API request failed.") from exc
        except ValueError as exc:
            # The SDK validates language code and format before any request.
            raise ASRProviderConfigurationError(
                f"Gnani STT rejected the adapter configuration: {exc}"
            ) from exc
        except OSError as exc:
            # Network failures (requests' exceptions derive from OSError).
            raise ASRProviderUnavailableError("Gnani STT could not be reached.") from exc
        except Exception as exc:
            raise ASRProviderError("Unexpected Gnani STT provider failure.") from exc

        if not isinstance(response, dict):
            raise ASRProviderError("Gnani STT returned an invalid response payload.")

        if response.get("success") is False:
            raise ASRProviderError("Gnani STT reported an unsuccessful transcription.")

        transcript_text = response.get("transcript")

        if not isinstance(transcript_text, str) or not transcript_text.strip():
            raise ASRProviderError("Gnani STT response did not contain a valid transcript.")

        provider_request_id = response.get("request_id")

        if provider_request_id is not None and not isinstance(
            provider_request_id,
            str,
        ):
            provider_request_id = str(provider_request_id)

        provider_metadata: dict[str, str | int | float | bool | None] = {
            "format": self._format,
            "requested_language": language_code,
        }
        for field in _METADATA_FIELDS:
            value = response.get(field)
            if value is None or isinstance(value, str | int | float | bool):
                provider_metadata[field] = value

        return Transcript(
            transcript_id=uuid4(),
            provider="gnani",
            provider_request_id=provider_request_id,
            language=language_code,
            detected_languages=[],
            text=transcript_text,
            segments=[],
            provider_metadata=provider_metadata,
            created_at=datetime.now(UTC),
        )


_: type[ASRProvider] = GnaniASRProvider
