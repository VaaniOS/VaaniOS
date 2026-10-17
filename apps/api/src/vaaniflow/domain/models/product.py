from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Product(DomainSchema):
    """
    Catalog product.

    Product resolution must consider identifiers such as SKU, brand,
    packaging, unit and aliases rather than relying on a generic name match.
    """

    product_id: UUID

    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)

    brand: str | None = None
    product_family: str | None = None
    category: str | None = None

    aliases: list[str] = Field(default_factory=list)

    unit: str = Field(min_length=1)
    packaging: str | None = None

    status: ProductStatus = ProductStatus.ACTIVE

    created_at: datetime
    updated_at: datetime
