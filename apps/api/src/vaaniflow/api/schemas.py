from datetime import datetime
from typing import Any, Literal
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


class ConfirmationView(BaseModel):
    confirmation_id: UUID
    status: str
    prompt: str
    warnings: list[str] = Field(default_factory=list)


class ClarificationView(BaseModel):
    """What was understood and what is missing; the next turn continues from this."""

    clarification_id: UUID
    reason_code: str
    reason: str
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    understood: dict[str, Any] = Field(default_factory=dict)


class DuplicateView(BaseModel):
    status: str
    reason: str
    duplicate_order_ids: list[UUID] = Field(default_factory=list)


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
    superseded_confirmation_ids: list[UUID] = Field(default_factory=list)
    superseded_clarification_ids: list[UUID] = Field(default_factory=list)
    confirmation: ConfirmationView | None = None
    clarification: ClarificationView | None = None
    duplicate_check: DuplicateView | None = None


class ApproveRequest(BaseModel):
    """Approve one specific pending approval of the run; its stored plan executes."""

    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    # Recorded for audit only; identity is not authentication and grants nothing.
    approved_by: UUID | None = None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: UUID
    rejected_by: UUID | None = None
    reason: str | None = None


class ClarifyRequest(BaseModel):
    """A new instruction for the run; it supersedes anything pending on it."""

    model_config = ConfigDict(extra="forbid")

    clarification: str = Field(min_length=1)


class ConfirmRequest(BaseModel):
    """
    A yes/no reply to the confirmation pending on this run. Without an id it
    answers the run's single pending confirmation; it never approves anything.
    """

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1)
    confirmation_id: UUID | None = None
    confirmed_by: UUID | None = None


class ResolveUnknownRequest(BaseModel):
    """
    Operator resolution of one UNKNOWN execution. ``attempt`` must match the
    execution's current attempt. SUCCEEDED is accepted only if read-back verifies
    a record committed by this operation; ``resolved_by`` is recorded, not trusted.
    """

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    outcome: Literal["SUCCEEDED", "FAILED"]
    reason: str = Field(min_length=1)
    resolved_by: UUID | None = None
    entity_id: UUID | None = None


class ManualHandoffRequest(BaseModel):
    reason: str = Field(min_length=1)
    operator_id: UUID | None = None
