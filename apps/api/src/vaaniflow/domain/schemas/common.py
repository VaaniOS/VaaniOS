from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DomainSchema(BaseModel):
    """Base configuration for all domain schemas."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


class ConfidenceSource(StrEnum):
    MODEL = "MODEL"
    RULE = "RULE"
    PROVIDER = "PROVIDER"
    HUMAN = "HUMAN"


class Confidence(DomainSchema):
    score: float = Field(ge=0.0, le=1.0)
    source: ConfidenceSource


class Actionability(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    BLOCKED = "BLOCKED"


class AmbiguitySeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NoiseLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AudioQualityLevel(StrEnum):
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    DEGRADED = "DEGRADED"
    POOR = "POOR"
    UNUSABLE = "UNUSABLE"


class UUIDModel(DomainSchema):
    """Domain schema containing a stable UUID identifier."""

    id: UUID