from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class QuoteStatus(StrEnum):
    DRAFT = "DRAFT"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Quote(DomainSchema):
    """
    Historical or current customer-specific price quote.

    A quote is evidence for pricing; it is not merely a value extracted
    from speech.
    """

    quote_id: UUID

    customer_id: UUID
    product_id: UUID

    unit: str = Field(min_length=1)

    unit_price: Decimal = Field(gt=0)
    currency: str = Field(min_length=1)

    quoted_on: date
    valid_until: date | None = None

    status: QuoteStatus

    customer_specific: bool = True

    created_at: datetime
    updated_at: datetime

    def is_applicable_on(self, day: date) -> bool:
        """
        True when this quote may price a transaction on ``day``: its status is
        VALID and ``day`` lies inside [quoted_on, valid_until]. A VALID status
        alone is not enough once the validity window has passed.
        """
        if self.status is not QuoteStatus.VALID:
            return False
        if day < self.quoted_on:
            return False
        return self.valid_until is None or day <= self.valid_until
