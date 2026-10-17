from __future__ import annotations

from io import BufferedIOBase
from typing import Protocol

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.domain.schemas.transcript import Transcript


class ASRProviderError(Exception):
    """Base error for ASR provider failures."""


class ASRProviderUnavailableError(ASRProviderError):
    """Raised when an ASR provider cannot currently process a request."""


class ASRProviderInvalidInputError(ASRProviderError):
    """Raised when the provider rejects the supplied audio input."""


class ASRProvider(Protocol):
    """
    Port for speech-to-text providers.

    Implementations translate provider-specific responses into the
    provider-neutral Transcript domain schema.
    """

    def transcribe(
        self,
        *,
        request: ASRInput,
        audio: BufferedIOBase,
    ) -> Transcript:
        """
        Transcribe supplied audio into the canonical Transcript model.

        Provider-specific payloads must not escape this boundary.
        """