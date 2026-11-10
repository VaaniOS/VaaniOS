"""
FFmpeg conversion of arbitrary input audio (e.g. Telegram Opus ``.oga``) to the
canonical 16 kHz mono PCM16 WAV that the UNDERSTAND audio pipeline expects.

Audio is passed through pipes only (no temporary files). The executable comes
from ``VAANIFLOW_FFMPEG`` or the ``PATH``; there is an explicit timeout, the
child process is killed and reaped on timeout, and errors carry a short,
sanitized reason — never the raw command line or environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping

FFMPEG_ENV = "VAANIFLOW_FFMPEG"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_INPUT_BYTES = 20 * 1024 * 1024  # Telegram's bot download limit is 20 MB
_STDERR_LIMIT = 300


class AudioConversionError(Exception):
    """Conversion failed. ``code``: FFMPEG_NOT_FOUND, INPUT_TOO_LARGE, EMPTY_INPUT,
    CONVERSION_TIMEOUT, CONVERSION_FAILED or EMPTY_OUTPUT."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_ffmpeg(environ: Mapping[str, str] | None = None) -> str:
    """The FFmpeg executable: ``VAANIFLOW_FFMPEG`` if set, else ``ffmpeg`` on PATH."""
    configured = (environ if environ is not None else os.environ).get(FFMPEG_ENV, "").strip()
    candidate = configured or "ffmpeg"
    resolved = shutil.which(candidate)
    if resolved is None:
        raise AudioConversionError(
            "FFMPEG_NOT_FOUND",
            "FFmpeg is not installed or not executable"
            + (f" at {FFMPEG_ENV}" if configured else " on PATH")
            + ".",
        )
    return resolved


def convert_to_pcm16_wav(
    audio: bytes,
    *,
    executable: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """Convert ``audio`` to 16 kHz mono PCM16 WAV bytes, or raise AudioConversionError."""
    if not audio:
        raise AudioConversionError("EMPTY_INPUT", "The audio file is empty.")
    if len(audio) > MAX_INPUT_BYTES:
        raise AudioConversionError("INPUT_TOO_LARGE", "The audio file is too large.")
    ffmpeg = executable or resolve_ffmpeg()
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        "pipe:1",
    ]
    try:
        # subprocess.run kills and reaps the child when the timeout expires.
        completed = subprocess.run(
            command, input=audio, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise AudioConversionError(
            "CONVERSION_TIMEOUT", f"Audio conversion took longer than {timeout:g} s."
        ) from None
    except OSError as exc:
        raise AudioConversionError(
            "FFMPEG_NOT_FOUND", f"FFmpeg could not be started ({type(exc).__name__})."
        ) from None
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        reason = detail[-1][:_STDERR_LIMIT] if detail else f"exit status {completed.returncode}"
        raise AudioConversionError("CONVERSION_FAILED", f"The audio could not be decoded: {reason}")
    if len(completed.stdout) <= 44:  # a WAV header without samples
        raise AudioConversionError("EMPTY_OUTPUT", "The audio contained no decodable sound.")
    return completed.stdout
