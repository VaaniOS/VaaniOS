from __future__ import annotations

from datetime import UTC, datetime
from io import BufferedIOBase, BytesIO
from uuid import uuid4

from gnani.stt import (
    APIError,
    AuthenticationError,
    GnaniSTTClient,
    InvalidAudioError,
)

from vaaniflow.application.ports.asr import (
    ASRProvider,
    ASRProviderError,
    ASRProviderInvalidInputError,
    ASRProviderUnavailableError,
)
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.transcript import Transcript


class GnaniASRProvider:
    """
    Gnani Vachana Speech-to-Text adapter.

    This adapter isolates the Gnani SDK from the VaaniFlow application
    and domain layers. Gnani-specific response payloads and exceptions
    are translated into provider-neutral VaaniFlow contracts.
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

        try:
            response = self._client.transcribe(
                BytesIO(audio_bytes),
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
        except Exception as exc:
            raise ASRProviderError("Unexpected Gnani STT provider failure.") from exc

        if not isinstance(response, dict):
            raise ASRProviderError("Gnani STT returned an invalid response payload.")

        transcript_text = response.get("transcript")

        if not isinstance(transcript_text, str) or not transcript_text.strip():
            raise ASRProviderError("Gnani STT response did not contain a valid transcript.")

        provider_request_id = response.get("request_id")

        if provider_request_id is not None and not isinstance(
            provider_request_id,
            str,
        ):
            provider_request_id = str(provider_request_id)

        return Transcript(
            transcript_id=uuid4(),
            provider="gnani",
            provider_request_id=provider_request_id,
            language=language_code,
            detected_languages=[language_code],
            text=transcript_text,
            segments=[],
            created_at=datetime.now(UTC),
        )


_: type[ASRProvider] = GnaniASRProvider
