from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import (
    AudioQualityLevel,
    DomainSchema,
    NoiseLevel,
)


class AudioMetadata(DomainSchema):
    """
    Metadata describing the original or processed audio artifact.

    The original audio must be preserved separately. This schema only
    describes the artifact; it does not contain the audio bytes.
    """

    artifact_id: UUID

    mime_type: str
    codec: str | None = None

    sample_rate_hz: int = Field(gt=0)
    channels: int = Field(gt=0)

    duration_ms: int = Field(gt=0)
    file_size_bytes: int = Field(gt=0)

    estimated_snr_db: float | None = None
    speech_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    silence_ratio: float | None = Field(default=None, ge=0.0, le=1.0)

    peak_level: float | None = None
    clipping_detected: bool = False

    noise_level: NoiseLevel
    quality_class: AudioQualityLevel