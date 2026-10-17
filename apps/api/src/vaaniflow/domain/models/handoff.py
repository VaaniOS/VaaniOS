from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class HandoffPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class HandoffStatus(StrEnum):
    CREATED = "CREATED"
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"

    RESUME_AUTOMATION = "RESUME_AUTOMATION"
    HUMAN_COMPLETED = "HUMAN_COMPLETED"


class HandoffCase(DomainSchema):
    """
    Structured escalation from automation to a human operator.

    The handoff packet must preserve what the user asked, what the system
    understood, what evidence it found, what it attempted, why it stopped,
    and what the operator should do next.
    """

    handoff_id: UUID

    run_id: UUID

    status: HandoffStatus
    priority: HandoffPriority

    reason: str = Field(min_length=1)

    customer_id: UUID | None = None

    original_request: str = Field(min_length=1)
    interpreted_request: dict[str, Any] = Field(default_factory=dict)

    uncertainties: list[str] = Field(default_factory=list)

    evidence: list[str] = Field(default_factory=list)

    attempted_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)

    recommended_action: str | None = None

    risk_summary: str | None = None

    assigned_to: UUID | None = None

    created_at: datetime
    resolved_at: datetime | None = None
