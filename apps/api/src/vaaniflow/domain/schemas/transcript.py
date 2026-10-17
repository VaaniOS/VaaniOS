from datetime import datetime
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import Confidence, DomainSchema


class TranscriptSegment(DomainSchema):
    """A time-aligned segment produced by an ASR provider."""

    segment_id: UUID

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    text: str = Field(min_length=1)

    language: str | None = None
    confidence: Confidence | None = None


class Transcript(DomainSchema):
    """ASR output associated with a voice run."""

    transcript_id: UUID

    provider: str
    provider_request_id: str | None = None

    language: str | None = None
    detected_languages: list[str] = Field(default_factory=list)

    text: str = Field(min_length=1)

    segments: list[TranscriptSegment] = Field(default_factory=list)

    created_at: datetime