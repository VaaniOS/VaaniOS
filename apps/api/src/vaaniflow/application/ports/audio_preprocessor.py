from __future__ import annotations

from io import BufferedIOBase
from typing import Protocol

from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
    AudioPreprocessingResult,
)


class AudioPreprocessorError(Exception):
    """Base error for audio preprocessing failures."""


class AudioPreprocessorUnavailableError(AudioPreprocessorError):
    """Raised when an audio preprocessing implementation is unavailable."""


class AudioPreprocessorInvalidInputError(AudioPreprocessorError):
    """Raised when the preprocessing input cannot be processed."""


class AudioPreprocessor(Protocol):
    """
    Port for audio preprocessing implementations.

    Implementations transform raw or previously processed audio into
    provider-neutral audio suitable for downstream ASR.

    Provider/library-specific details must not escape this boundary.
    """

    def preprocess(
        self,
        *,
        request: AudioPreprocessingInput,
        audio: BufferedIOBase,
    ) -> tuple[AudioPreprocessingResult, BufferedIOBase]:
        """
        Preprocess the supplied audio and return its resulting artifact
        metadata together with the resulting audio stream.
        """