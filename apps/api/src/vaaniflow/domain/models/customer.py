from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class CustomerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class Customer(DomainSchema):
    """
    Business customer resolved from a user's request.

    Resolution may produce multiple candidates; the context layer must not
    arbitrarily select one when identity remains ambiguous.
    """

    customer_id: UUID

    name: str = Field(min_length=1)

    aliases: list[str] = Field(default_factory=list)

    phone: str | None = None
    email: str | None = None

    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None

    tax_id: str | None = None

    status: CustomerStatus = CustomerStatus.ACTIVE

    created_at: datetime
    updated_at: datetime
