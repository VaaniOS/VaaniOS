from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class Warehouse(DomainSchema):
    """Warehouse location storing physical inventory."""

    warehouse_id: UUID
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    address: str | None = None
    is_active: bool = True
