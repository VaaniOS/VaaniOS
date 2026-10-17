from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderItem(DomainSchema):
    """One product line within an order."""

    item_id: UUID

    product_id: UUID

    quantity: int = Field(gt=0)
    unit: str = Field(min_length=1)

    unit_price: Decimal = Field(gt=0)

    line_total: Decimal = Field(gt=0)


class Order(DomainSchema):
    """
    Business order created from a validated semantic request.

    This model represents business state, not the agent's proposed plan.
    """

    order_id: UUID

    customer_id: UUID

    recipient_name: str | None = None
    delivery_address: str | None = None

    items: list[OrderItem] = Field(min_length=1)

    currency: str = Field(min_length=1)

    subtotal: Decimal = Field(gt=0)

    status: OrderStatus

    source_run_id: UUID | None = None

    created_at: datetime
    updated_at: datetime
