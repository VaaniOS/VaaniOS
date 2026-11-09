from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType


class CreateRunRequest(BaseModel):
    text: str | None = None


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: VoiceRunStatus
    created_at: datetime


class ProcessRunRequest(BaseModel):
    text: str | None = None
    is_approved: bool = False
    approved_by: UUID | None = None
    faults: dict[str, Any] = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    run_id: UUID
    status: VoiceRunStatus
    message: str
    decision: DecisionType | None = None
    decision_reason: str | None = None
    snapshot_version: str | None = None
    approval_required: bool = False
    approval_id: UUID | None = None
    handoff_case_id: UUID | None = None
    execution_success: bool | None = None


class ApproveRequest(BaseModel):
    approved_by: UUID | None = None
    snapshot_version: str | None = None


class ClarifyRequest(BaseModel):
    clarification: str = Field(min_length=1)


class ManualHandoffRequest(BaseModel):
    reason: str = Field(min_length=1)
    operator_id: UUID | None = None
