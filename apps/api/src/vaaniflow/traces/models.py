from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class TraceStage(StrEnum):
    """Lifecycle stages captured during voice-to-action execution."""

    INGESTED = "INGESTED"
    AUDIO_ANALYZED = "AUDIO_ANALYZED"
    AUDIO_PROCESSED = "AUDIO_PROCESSED"
    TRANSCRIBED = "TRANSCRIBED"
    SEMANTIC_COMPILED = "SEMANTIC_COMPILED"
    INPUT_EVALUATED = "INPUT_EVALUATED"
    CONTEXT_RESOLVED = "CONTEXT_RESOLVED"
    VALIDATED = "VALIDATED"
    RISK_ASSESSED = "RISK_ASSESSED"
    DECISION_MADE = "DECISION_MADE"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    TOOL_EXECUTED = "TOOL_EXECUTED"
    VERIFIED = "VERIFIED"
    HANDOFF_CREATED = "HANDOFF_CREATED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class TraceEvent(DomainSchema):
    """
    Structured observability record for a single step in a voice run.

    Enables complete provenance tracking: "Why did the system take this action?"
    """

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    stage: TraceStage
    timestamp: datetime
    latency_ms: int | None = Field(default=None, ge=0)

    component: str | None = None
    input_ref: str | None = None
    output_summary: str | None = None

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision: str | None = None

    tool_name: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None

    error_code: str | None = None
    error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class RunTrace(DomainSchema):
    """Complete chronological audit trace for an entire voice run."""

    run_id: UUID
    events: list[TraceEvent] = Field(default_factory=list)
    total_latency_ms: int = Field(default=0, ge=0)
    started_at: datetime
    completed_at: datetime | None = None
