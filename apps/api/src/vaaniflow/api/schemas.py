from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.domain.schemas.semantic import Ambiguity
from vaaniflow.domain.schemas.understand import EvaluationReason
from vaaniflow.execution.plan import StepOutcome


class CreateRunRequest(BaseModel):
    text: str | None = None


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: VoiceRunStatus
    created_at: datetime


class ProcessRunRequest(BaseModel):
    """Only the instruction. Approval is never a client-supplied flag (see /approve)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None


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
    actionability: str | None = None
    evaluation_reasons: list[EvaluationReason] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    planned_tools: list[str] = Field(default_factory=list)
    unsupported_actions: list[str] = Field(default_factory=list)
    excluded_negated_actions: list[str] = Field(default_factory=list)
    executed_tools: list[str] = Field(default_factory=list)
    # Per-tool evidence for an executed plan: VERIFIED / FAILED / UNKNOWN / NOT_ATTEMPTED.
    tool_outcomes: list[StepOutcome] = Field(default_factory=list)
    superseded_approval_ids: list[UUID] = Field(default_factory=list)


class ApproveRequest(BaseModel):
    """Approve one specific pending approval of the run; its stored plan executes."""

    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    approved_by: UUID | None = None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    rejected_by: UUID | None = None


class ClarifyRequest(BaseModel):
    clarification: str = Field(min_length=1)


class ManualHandoffRequest(BaseModel):
    reason: str = Field(min_length=1)
    operator_id: UUID | None = None
