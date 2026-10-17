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
from vaaniflow.domain.schemas.audio import AudioMetadata


class LocalAudioPreprocessor:
    """
    Deterministic local audio preprocessor for PCM WAV input.

    The first concrete implementation intentionally performs only
    structural audio normalization:

    - validates WAV input;
    - converts audio to mono;
    - converts samples to 16-bit PCM;
    - resamples audio to 16 kHz;
    - emits a canonical WAV artifact.

    Noise suppression, VAD, dereverberation, speech enhancement,
    and quality analysis are separate concerns and are not silently
    performed here.
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
            processed_audio = self._normalize_wav(raw_audio)
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

        metadata = self._build_metadata(
            request=request,
            artifact_id=artifact_id,
            wav_bytes=processed_audio,
        )

        result = AudioPreprocessingResult(
            artifact_id=artifact_id,
            storage_ref=self._build_storage_ref(
                source_storage_ref=request.storage_ref,
            ),
            metadata=metadata,
        )

        return result, io.BytesIO(processed_audio)

    def _normalize_wav(self, raw_audio: bytes) -> bytes:
        """
        Decode, normalize, resample, and encode a WAV artifact.

        SoundFile handles WAV decoding/encoding while SciPy performs
        polyphase resampling.
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

        # Convert multi-channel audio to mono by averaging channels.
        mono = np.mean(samples, axis=1, dtype=np.float32)

        if sample_rate != self.TARGET_SAMPLE_RATE_HZ:
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
        mono = np.clip(mono, -1.0, 1.0)

        output = io.BytesIO()

        sf.write(
            output,
            mono,
            self.TARGET_SAMPLE_RATE_HZ,
            format="WAV",
            subtype="PCM_16",
        )

        return output.getvalue()

    def _build_metadata(
        self,
        *,
        request: AudioPreprocessingInput,
        artifact_id: UUID,
        wav_bytes: bytes,
    ) -> AudioMetadata:
        """
        Build metadata from the resulting canonical WAV artifact.

        Existing source quality metadata is carried forward because this
        implementation does not perform quality analysis.
        """
        source_metadata = request.metadata

        with io.BytesIO(wav_bytes) as wav_stream:
            samples, sample_rate = sf.read(
                wav_stream,
                dtype="int16",
                always_2d=True,
            )

        frame_count = samples.shape[0]
        channels = samples.shape[1]

        if frame_count <= 0:
            raise AudioPreprocessorInvalidInputError("Processed WAV contains no frames.")

        duration_ms = round(
            frame_count / sample_rate * 1000,
        )

        return AudioMetadata(
            artifact_id=artifact_id,
            mime_type="audio/wav",
            codec="pcm_s16le",
            sample_rate_hz=sample_rate,
            channels=channels,
            duration_ms=max(duration_ms, 1),
            file_size_bytes=len(wav_bytes),
            estimated_snr_db=source_metadata.estimated_snr_db,
            speech_ratio=source_metadata.speech_ratio,
            silence_ratio=source_metadata.silence_ratio,
            peak_level=source_metadata.peak_level,
            clipping_detected=source_metadata.clipping_detected,
            noise_level=source_metadata.noise_level,
            quality_class=source_metadata.quality_class,
        )

    def _build_storage_ref(
        self,
        *,
        source_storage_ref: str,
    ) -> str:
        """
        Create a deterministic namespace for locally processed artifacts.
        """
        if source_storage_ref.startswith("local://"):
            relative_path = source_storage_ref.removeprefix("local://")
            return f"local://processed/{relative_path}"

        return f"local://processed/{uuid4()}.wav"


_: type[AudioPreprocessor] = LocalAudioPreprocessor
