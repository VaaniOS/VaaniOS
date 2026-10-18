from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from vaaniflow.domain.models.customer import Customer, CustomerStatus
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.models.product import Product, ProductStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tax import TaxRule
from vaaniflow.domain.models.warehouse import Warehouse


class BusinessDataError(Exception):
    """Base error for business data repository failures."""


class EntityNotFoundError(BusinessDataError):
    """Raised when an explicitly requested business entity does not exist."""


class CustomerRepository(Protocol):
    """Port for customer data retrieval."""

    def get_by_id(self, *, customer_id: UUID) -> Customer | None:
        """Retrieve customer by unique ID."""
        ...

    def search(
        self,
        *,
        query: str,
        status: CustomerStatus | None = CustomerStatus.ACTIVE,
    ) -> list[Customer]:
        """Search customers by name, alias, phone, or tax ID."""
        ...

    def list_all(self) -> list[Customer]:
        """List all customers."""
        ...


class ProductRepository(Protocol):
    """Port for product catalog data retrieval."""

    def get_by_id(self, *, product_id: UUID) -> Product | None:
        """Retrieve product by unique ID."""
        ...

    def get_by_sku(self, *, sku: str) -> Product | None:
        """Retrieve product by exact SKU."""
        ...

    def search(
        self,
        *,
        query: str,
        status: ProductStatus | None = ProductStatus.ACTIVE,
    ) -> list[Product]:
        """Search products by name, brand, SKU, family, or alias."""
        ...

    def list_all(self) -> list[Product]:
        """List all products."""
        ...


class QuoteRepository(Protocol):
    """Port for quote retrieval."""

    def get_by_id(self, *, quote_id: UUID) -> Quote | None:
        """Retrieve quote by unique ID."""
        ...

    def find_quotes(
        self,
        *,
        customer_id: UUID | None = None,
        product_id: UUID | None = None,
        status: QuoteStatus | None = None,
        quoted_on: date | None = None,
        as_of_date: date | None = None,
    ) -> list[Quote]:
        """
        Find quotes matching customer, product, date, and validity constraints.
        """
        ...

    def list_all(self) -> list[Quote]:
        """List all quotes."""
        ...


class InventoryRepository(Protocol):
    """Port for inventory stock retrieval."""

    def get_by_id(self, *, inventory_id: UUID) -> Inventory | None:
        """Retrieve inventory record by ID."""
        ...

    def get_by_product(
        self,
        *,
        product_id: UUID,
        warehouse_id: UUID | None = None,
    ) -> list[Inventory]:
        """Retrieve stock for a product across warehouses or at a specific warehouse."""
        ...

    def list_all(self) -> list[Inventory]:
        """List all inventory records."""
        ...


class WarehouseRepository(Protocol):
    """Port for warehouse retrieval."""

    def get_by_id(self, *, warehouse_id: UUID) -> Warehouse | None:
        """Retrieve warehouse by ID."""
        ...

    def get_by_code(self, *, code: str) -> Warehouse | None:
        """Retrieve warehouse by code."""
        ...

    def list_all(self) -> list[Warehouse]:
        """List all warehouses."""
        ...


class TaxRuleRepository(Protocol):
    """Port for tax rules lookup."""

    def get_rule(
        self,
        *,
        category: str,
        jurisdiction: str = "KA",
        as_of_date: date | None = None,
    ) -> TaxRule | None:
        """Retrieve applicable tax rule for category and jurisdiction."""
        ...

    def list_all(self) -> list[TaxRule]:
        """List all tax rules."""
        ...
