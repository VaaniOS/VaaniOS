from __future__ import annotations

from datetime import UTC, datetime
from io import BufferedIOBase
from uuid import uuid4

from vaaniflow.application.ports.asr import ASRProvider
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.transcript import Transcript


class MockASR:
    """
    Deterministic ASR provider used for local development and testing.

    This implementation deliberately does not perform speech recognition.
    It returns a predictable Transcript through the same provider-neutral
    interface that a real ASR provider must implement.
    """

    def __init__(
        self,
        *,
        text: str = "Test transcription",
        provider: str = "mock",
    ) -> None:
        if not text:
            raise ValueError("Mock ASR text cannot be empty.")

        if not provider:
            raise ValueError("Mock ASR provider name cannot be empty.")

        self._text = text
        self._provider = provider

    def transcribe(
        self,
        *,
        request: ASRInput,
        audio: BufferedIOBase,
    ) -> Transcript:
        """
        Return a deterministic Transcript.

        The audio stream is consumed to mirror the behavior of a real
        provider adapter. The actual bytes are intentionally ignored.
        """

        audio.read()

        language = request.language_hint

        detected_languages = [language] if language is not None else []

        return Transcript(
            transcript_id=uuid4(),
            provider=self._provider,
            provider_request_id=None,
            language=language,
            detected_languages=detected_languages,
            text=self._text,
            segments=[],
            created_at=datetime.now(UTC),
        )


_: type[ASRProvider] = MockASR