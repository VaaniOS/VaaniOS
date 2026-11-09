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
    # A newer instruction on the same run replaced this request; never executable.
    SUPERSEDED = "SUPERSEDED"


class Approval(DomainSchema):
    """
    Explicit human approval bound to a particular business-state snapshot.

    If the underlying transaction changes after approval, the approval may
    no longer be valid.
    """

    approval_id: UUID

    # What is being approved: the run and the exact plan (P2-B audit linkage).
    run_id: UUID | None = None
    plan_id: UUID | None = None
    plan_fingerprint: str | None = None

    # Business records the approved plan produced (set after execution).
    order_id: UUID | None = None
    invoice_id: UUID | None = None
    dispatch_id: UUID | None = None

    # None when no identity is known; the system never fabricates one.
    requested_by: UUID | None = None
    approved_by: UUID | None = None
    rejected_by: UUID | None = None
    # Identities above are claims recorded for audit. There is no authentication
    # layer yet, so they are never verified and never grant authorization.
    actor_authenticated: bool = False

    status: ApprovalStatus

    snapshot_version: str = Field(min_length=1)
    # Business snapshot re-computed at approval time (equal to snapshot_version
    # for an executed approval; an approval whose snapshot changed expires).
    approved_snapshot_version: str | None = None

    requested_at: datetime
    resolved_at: datetime | None = None

    # Why the approval reached a terminal non-approved state.
    rejection_reason: str | None = None
    expiry_reason: str | None = None
    # The approval that replaced this one when a newer instruction superseded it.
    superseded_by: UUID | None = None
