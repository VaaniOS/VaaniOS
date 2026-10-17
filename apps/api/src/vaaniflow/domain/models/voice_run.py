from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class VoiceRunStatus(StrEnum):
    CREATED = "CREATED"

    AUDIO_RECEIVED = "AUDIO_RECEIVED"
    PROCESSING = "PROCESSING"
    TRANSCRIBED = "TRANSCRIBED"

    SEMANTIC_READY = "SEMANTIC_READY"
    CONTEXT_READY = "CONTEXT_READY"
    VALIDATED = "VALIDATED"
    DECIDED = "DECIDED"

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"

    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    HANDOFF = "HANDOFF"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class VoiceRun(DomainSchema):
    """
    Aggregate-level state for one end-to-end voice workflow.

    This is the lifecycle container. Individual artifacts such as audio,
    transcript, semantic state, validation results, tool executions and
    verification records remain separate domain objects.
    """

    run_id: UUID = Field(default_factory=uuid4)

    status: VoiceRunStatus = VoiceRunStatus.CREATED

    audio_artifact_id: UUID | None = None
    transcript_id: UUID | None = None
    semantic_state_id: UUID | None = None

    created_at: datetime
    updated_at: datetime

    failure_code: str | None = None
    failure_message: str | None = None
