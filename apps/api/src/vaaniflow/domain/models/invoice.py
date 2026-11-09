from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class InvoiceItem(DomainSchema):
    """One product line on an invoice."""

    item_id: UUID

    product_id: UUID

    quantity: int = Field(gt=0)
    unit: str = Field(min_length=1)

    unit_price: Decimal = Field(gt=0)

    line_total: Decimal = Field(gt=0)


class Invoice(DomainSchema):
    """
    Invoice business state.

    Tax values must come from the business-rules layer rather than being
    invented by the semantic compiler or LLM.
    """

    invoice_id: UUID

    order_id: UUID
    customer_id: UUID

    items: list[InvoiceItem] = Field(min_length=1)

    currency: str = Field(min_length=1)

    subtotal: Decimal = Field(gt=0)

    tax_total: Decimal = Field(ge=0)
    total: Decimal = Field(gt=0)

    status: InvoiceStatus

    # Key of the write that created this record; used to reconcile UNKNOWN outcomes.
    idempotency_key: str | None = None

    created_at: datetime
    updated_at: datetime
