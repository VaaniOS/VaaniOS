from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.models.customer import Customer
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.models.product import Product
from vaaniflow.domain.models.quote import Quote
from vaaniflow.domain.schemas.common import DomainSchema


class ResolvedCustomer(DomainSchema):
    customer: Customer
    resolution_id: UUID
    resolved_at: datetime


class ResolvedProduct(DomainSchema):
    product: Product
    resolution_id: UUID
    resolved_at: datetime


class ResolvedQuote(DomainSchema):
    quote: Quote
    resolution_id: UUID
    resolved_at: datetime


class ResolvedInventory(DomainSchema):
    inventory: Inventory
    resolution_id: UUID
    resolved_at: datetime


class ResolvedPrice(DomainSchema):
    product_id: UUID
    customer_id: UUID
    unit: str
    unit_price: Decimal = Field(gt=0)
    currency: str = Field(min_length=1)
    source_quote_id: UUID | None = None
    resolved_on: date


class BusinessContext(DomainSchema):
    context_id: UUID
    run_id: UUID
    customer: ResolvedCustomer | None = None
    products: list[ResolvedProduct] = Field(default_factory=list)
    quotes: list[ResolvedQuote] = Field(default_factory=list)
    inventory: list[ResolvedInventory] = Field(default_factory=list)
    resolved_price: ResolvedPrice | None = None
    unresolved_references: list[str] = Field(default_factory=list)
    resolution_errors: list[str] = Field(default_factory=list)
    resolved_at: datetime