from io import BytesIO
from uuid import uuid4

from vaaniflow.application.schemas.audio_preprocessing import (
    AudioPreprocessingInput,
    AudioPreprocessingResult,
)
from vaaniflow.application.services.preprocess_audio import (
    PreprocessAudioService,
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


class InMemoryArtifactStorage:
    def __init__(self) -> None:
        self._artifacts: dict[str, bytes] = {}

    def store(
        self,
        *,
        artifact,
        data: BytesIO,
    ) -> None:
        self._artifacts[artifact.storage_ref] = data.read()

    def open(self, *, storage_ref: str) -> BytesIO:
        return BytesIO(self._artifacts[storage_ref])

    def delete(self, *, storage_ref: str) -> None:
        del self._artifacts[storage_ref]


class RecordingAudioPreprocessor:
    def __init__(self) -> None:
        self.request: AudioPreprocessingInput | None = None
        self.audio_bytes: bytes | None = None

    def preprocess(
        self,
        *,
        request: AudioPreprocessingInput,
        audio: BytesIO,
    ) -> tuple[AudioPreprocessingResult, BytesIO]:
        self.request = request
        self.audio_bytes = audio.read()

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
            source_artifact_id=request.artifact_id,
        )

        return result, BytesIO(b"processed audio bytes")


def test_preprocess_audio_retrieves_processes_and_stores_audio() -> None:
    storage = InMemoryArtifactStorage()
    preprocessor = RecordingAudioPreprocessor()

    request = make_preprocessing_input()

    storage.store(
        artifact=type(
            "SourceArtifact",
            (),
            {"storage_ref": request.storage_ref},
        )(),
        data=BytesIO(b"raw audio bytes"),
    )

    service = PreprocessAudioService(
        artifact_storage=storage,
        audio_preprocessor=preprocessor,
    )

    result = service.execute(request=request)

    assert result.storage_ref == "local://audio/processed.wav"
    assert preprocessor.request == request
    assert preprocessor.audio_bytes == b"raw audio bytes"
    assert storage._artifacts["local://audio/processed.wav"] == b"processed audio bytes"


def test_preprocess_audio_returns_processed_metadata() -> None:
    storage = InMemoryArtifactStorage()
    preprocessor = RecordingAudioPreprocessor()

    request = make_preprocessing_input()

    storage.store(
        artifact=type(
            "SourceArtifact",
            (),
            {"storage_ref": request.storage_ref},
        )(),
        data=BytesIO(b"raw audio bytes"),
    )

    service = PreprocessAudioService(
        artifact_storage=storage,
        audio_preprocessor=preprocessor,
    )

    result = service.execute(request=request)

    assert result.metadata.quality_class == AudioQualityLevel.GOOD
    assert result.metadata.noise_level == NoiseLevel.LOW
