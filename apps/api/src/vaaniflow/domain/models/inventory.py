from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from vaaniflow.domain.schemas.common import DomainSchema


class Inventory(DomainSchema):
    """
    Inventory state for one product at one warehouse.

    available_quantity represents currently sellable/available stock.
    reserved_quantity represents stock already committed elsewhere.
    """

    inventory_id: UUID

    product_id: UUID
    warehouse_id: UUID

    available_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)

    updated_at: datetime

    @model_validator(mode="after")
    def validate_quantities(self) -> "Inventory":
        if self.reserved_quantity > self.available_quantity:
            raise ValueError(
                "reserved_quantity cannot exceed available_quantity"
            )

        return self