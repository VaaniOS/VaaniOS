from datetime import datetime
from enum import StrEnum
from uuid import UUID

from vaaniflow.domain.schemas.common import DomainSchema


class DispatchStatus(StrEnum):
    PREPARED = "PREPARED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Dispatch(DomainSchema):
    """
    Dispatch state.

    A successful API acknowledgement does not automatically mean the
    dispatch is verified. Verification is represented separately.
    """

    dispatch_id: UUID

    order_id: UUID
    customer_id: UUID

    warehouse_id: UUID

    status: DispatchStatus

    recipient_name: str | None = None
    delivery_address: str | None = None

    created_at: datetime
    updated_at: datetime