from __future__ import annotations

import io
from fractions import Fraction
from uuid import UUID, uuid4

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from vaaniflow.application.ports.audio_preprocessor import (
    AudioPreprocessor,
    AudioPreprocessorInvalidInputError,
)
from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
    AudioPreprocessingResult,
)
from vaaniflow.audio.quality import analyze_quality, detect_clipping
from vaaniflow.domain.schemas.audio import AudioMetadata

OPERATION_DECODE = "decode_wav"
OPERATION_DOWNMIX = "downmix_mono"
OPERATION_RESAMPLE = "resample_16khz"
OPERATION_CLIP_GUARD = "clip_guard"
OPERATION_ENCODE = "encode_pcm16"
OPERATION_ANALYZE = "analyze_quality"


class LocalAudioPreprocessor:
    """
    Deterministic local audio preprocessor for PCM WAV input.

    The first concrete implementation intentionally performs only
    structural audio normalization:

    - validates WAV input;
    - converts audio to mono;
    - converts samples to 16-bit PCM;
    - resamples audio to 16 kHz;
    - emits a canonical WAV artifact;
    - measures the processed artifact's quality metadata
      (``vaaniflow.audio.quality``) instead of trusting the caller's.

    Noise suppression, VAD trimming, dereverberation and speech
    enhancement are not performed. The applied operations are recorded
    on the result so lineage stays explicit.
    """

    TARGET_SAMPLE_RATE_HZ = 16_000
    TARGET_CHANNELS = 1
    TARGET_SAMPLE_WIDTH_BYTES = 2

    def preprocess(
        self,
        *,
        request: AudioPreprocessingInput,
        audio: io.BufferedIOBase,
    ) -> tuple[AudioPreprocessingResult, io.BytesIO]:
        """
        Normalize a WAV audio stream into canonical ASR input format.

        Returns a new in-memory WAV stream together with its canonical
        artifact metadata.
        """
        raw_audio = audio.read()

        if not raw_audio:
            raise AudioPreprocessorInvalidInputError("Audio input cannot be empty.")

        try:
            processed_audio, source_clipping, operations = self._normalize_wav(raw_audio)
        except (
            RuntimeError,
            TypeError,
            ValueError,
            sf.LibsndfileError,
        ) as exc:
            raise AudioPreprocessorInvalidInputError(
                "Audio input is not a valid supported PCM WAV stream."
            ) from exc

        artifact_id = uuid4()

        metadata = describe_wav(
            artifact_id=artifact_id,
            wav_bytes=processed_audio,
            clipping_detected=source_clipping,
        )

        result = AudioPreprocessingResult(
            artifact_id=artifact_id,
            storage_ref=self._build_storage_ref(artifact_id=artifact_id),
            metadata=metadata,
            source_artifact_id=request.artifact_id,
            applied_operations=[*operations, OPERATION_ANALYZE],
        )

        return result, io.BytesIO(processed_audio)

    def _normalize_wav(self, raw_audio: bytes) -> tuple[bytes, bool, list[str]]:
        """
        Decode, normalize, resample, and encode a WAV artifact.

        SoundFile handles WAV decoding/encoding while SciPy performs
        polyphase resampling. Returns the WAV bytes, whether the decoded
        source was clipped, and the operations applied.
        """
        source = io.BytesIO(raw_audio)

        samples, sample_rate = sf.read(
            source,
            dtype="float32",
            always_2d=True,
        )

        if samples.size == 0:
            raise AudioPreprocessorInvalidInputError("WAV audio contains no samples.")

        if sample_rate <= 0:
            raise AudioPreprocessorInvalidInputError("WAV sample rate must be positive.")

        if samples.shape[1] <= 0:
            raise AudioPreprocessorInvalidInputError("WAV channel count must be positive.")

        operations = [OPERATION_DECODE]
        source_clipping = detect_clipping(samples.reshape(-1))

        # Convert multi-channel audio to mono by averaging channels.
        mono = np.mean(samples, axis=1, dtype=np.float32)
        if samples.shape[1] > 1:
            operations.append(OPERATION_DOWNMIX)

        if sample_rate != self.TARGET_SAMPLE_RATE_HZ:
            operations.append(OPERATION_RESAMPLE)
            ratio = Fraction(
                self.TARGET_SAMPLE_RATE_HZ,
                sample_rate,
            )

            mono = resample_poly(
                mono,
                ratio.numerator,
                ratio.denominator,
            ).astype(np.float32)

        # Clip before PCM conversion so out-of-range floating-point
        # samples cannot wrap during quantization.
        if np.any(np.abs(mono) > 1.0):
            operations.append(OPERATION_CLIP_GUARD)
        mono = np.clip(mono, -1.0, 1.0)

        output = io.BytesIO()

        sf.write(
            output,
            mono,
            self.TARGET_SAMPLE_RATE_HZ,
            format="WAV",
            subtype="PCM_16",
        )

        operations.append(OPERATION_ENCODE)
        return output.getvalue(), source_clipping, operations

    def _build_storage_ref(self, *, artifact_id: UUID) -> str:
        """
        Unique, write-once location for a processed artifact.

        Keyed by the new artifact id so re-processing never overwrites a
        previously processed artifact (ADR-016).
        """
        return f"local://processed/{artifact_id}.wav"


def describe_wav(
    *,
    artifact_id: UUID,
    wav_bytes: bytes,
    clipping_detected: bool | None = None,
) -> AudioMetadata:
    """
    Measure AudioMetadata for a WAV byte stream.

    ``clipping_detected`` lets callers report clipping measured on an
    earlier (pre-normalisation) signal; otherwise it is measured here.
    """
    with io.BytesIO(wav_bytes) as wav_stream:
        info = sf.info(wav_stream)
        wav_stream.seek(0)
        samples, sample_rate = sf.read(wav_stream, dtype="float32", always_2d=True)

    if samples.shape[0] <= 0:
        raise AudioPreprocessorInvalidInputError("WAV contains no frames.")

    mono = np.mean(samples, axis=1, dtype=np.float32)
    analysis = analyze_quality(mono, sample_rate, clipping_detected=clipping_detected)

    return AudioMetadata(
        artifact_id=artifact_id,
        mime_type="audio/wav",
        codec="pcm_s16le" if info.subtype == "PCM_16" else info.subtype.casefold(),
        sample_rate_hz=sample_rate,
        channels=samples.shape[1],
        duration_ms=analysis.duration_ms,
        file_size_bytes=len(wav_bytes),
        estimated_snr_db=analysis.estimated_snr_db,
        speech_ratio=analysis.speech_ratio,
        silence_ratio=analysis.silence_ratio,
        peak_level=analysis.peak_level_dbfs,
        clipping_detected=analysis.clipping_detected,
        noise_level=analysis.noise_level,
        quality_class=analysis.quality_class,
    )


_: type[AudioPreprocessor] = LocalAudioPreprocessor
