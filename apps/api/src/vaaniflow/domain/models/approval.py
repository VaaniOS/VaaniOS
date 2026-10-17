from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class ApprovalStatus(StrEnum):
    REQUESTED = "REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Approval(DomainSchema):
    """
    Explicit human approval bound to a particular business-state snapshot.

    If the underlying transaction changes after approval, the approval may
    no longer be valid.
    """

    approval_id: UUID

    order_id: UUID | None = None
    invoice_id: UUID | None = None

    requested_by: UUID
    approved_by: UUID | None = None

    status: ApprovalStatus

    snapshot_version: str = Field(min_length=1)

    requested_at: datetime
    resolved_at: datetime | None = None
