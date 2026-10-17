from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import Confidence, DomainSchema


class ResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"


class ResolutionCandidate(DomainSchema):
    candidate_id: UUID
    entity_id: UUID
    display_name: str = Field(min_length=1)
    confidence: Confidence
    evidence: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ResolutionResult(DomainSchema):
    resolution_id: UUID
    entity_type: str = Field(min_length=1)
    status: ResolutionStatus
    query: str = Field(min_length=1)
    selected_entity_id: UUID | None = None
    candidates: list[ResolutionCandidate] = Field(default_factory=list)
    reason: str = Field(min_length=1)