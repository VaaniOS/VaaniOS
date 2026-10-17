from io import BytesIO
from uuid import uuid4

from vaaniflow.application.ports.audio_preprocessor import AudioPreprocessor
from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
    AudioPreprocessingResult,
)
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    NoiseLevel,
)


def make_preprocessing_input() -> AudioPreprocessingInput:
    artifact_id = uuid4()

    return AudioPreprocessingInput(
        artifact_id=artifact_id,
        storage_ref="local://audio/raw.wav",
        metadata=AudioMetadata(
            artifact_id=artifact_id,
            mime_type="audio/wav",
            codec="pcm_s16le",
            sample_rate_hz=16000,
            channels=1,
            duration_ms=1000,
            file_size_bytes=32000,
            estimated_snr_db=10.0,
            speech_ratio=0.7,
            silence_ratio=0.3,
            peak_level=-3.0,
            clipping_detected=False,
            noise_level=NoiseLevel.MEDIUM,
            quality_class=AudioQualityLevel.ACCEPTABLE,
        ),
    )


class MockAudioPreprocessor:
    """Minimal test implementation of the AudioPreprocessor protocol."""

    def preprocess(
        self,
        *,
        request: AudioPreprocessingInput,
        audio: BytesIO,
    ) -> tuple[AudioPreprocessingResult, BytesIO]:
        assert request.storage_ref == "local://audio/raw.wav"
        assert audio.read() == b"raw audio bytes"

        artifact_id = uuid4()

        metadata = AudioMetadata(
            artifact_id=artifact_id,
            mime_type="audio/wav",
            codec="pcm_s16le",
            sample_rate_hz=16000,
            channels=1,
            duration_ms=1000,
            file_size_bytes=34000,
            estimated_snr_db=18.0,
            speech_ratio=0.8,
            silence_ratio=0.2,
            peak_level=-1.0,
            clipping_detected=False,
            noise_level=NoiseLevel.LOW,
            quality_class=AudioQualityLevel.GOOD,
        )

        result = AudioPreprocessingResult(
            artifact_id=artifact_id,
            storage_ref="local://audio/processed.wav",
            metadata=metadata,
        )

        return result, BytesIO(b"processed audio bytes")


def test_audio_preprocessor_protocol_can_be_implemented() -> None:
    preprocessor: AudioPreprocessor = MockAudioPreprocessor()

    result, processed_audio = preprocessor.preprocess(
        request=make_preprocessing_input(),
        audio=BytesIO(b"raw audio bytes"),
    )

    assert isinstance(result, AudioPreprocessingResult)
    assert result.storage_ref == "local://audio/processed.wav"
    assert processed_audio.read() == b"processed audio bytes"