from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from vaaniflow.domain.models.approval import Approval
from vaaniflow.domain.models.customer import Customer, CustomerStatus
from vaaniflow.domain.models.dispatch import Dispatch
from vaaniflow.domain.models.handoff import HandoffCase
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.models.invoice import Invoice
from vaaniflow.domain.models.order import Order
from vaaniflow.domain.models.product import Product, ProductStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tax import TaxRule
from vaaniflow.domain.models.tool_execution import ToolExecution
from vaaniflow.domain.models.verification import Verification
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


class OrderRepository(Protocol):
    """Port for order persistence and retrieval."""

    def save(self, *, order: Order) -> None:
        """Save or update an order."""
        ...

    def get_by_id(self, *, order_id: UUID) -> Order | None:
        """Retrieve order by ID."""
        ...

    def list_by_customer(self, *, customer_id: UUID) -> list[Order]:
        """List orders for a customer."""
        ...

    def list_all(self) -> list[Order]:
        """List all orders."""
        ...


class InvoiceRepository(Protocol):
    """Port for invoice persistence and retrieval."""

    def save(self, *, invoice: Invoice) -> None:
        """Save or update an invoice."""
        ...

    def get_by_id(self, *, invoice_id: UUID) -> Invoice | None:
        """Retrieve invoice by ID."""
        ...

    def get_by_order_id(self, *, order_id: UUID) -> Invoice | None:
        """Retrieve invoice associated with an order."""
        ...

    def list_all(self) -> list[Invoice]:
        """List all invoices."""
        ...


class DispatchRepository(Protocol):
    """Port for dispatch record persistence and retrieval."""

    def save(self, *, dispatch: Dispatch) -> None:
        """Save or update a dispatch record."""
        ...

    def get_by_id(self, *, dispatch_id: UUID) -> Dispatch | None:
        """Retrieve dispatch by ID."""
        ...

    def get_by_order_id(self, *, order_id: UUID) -> Dispatch | None:
        """Retrieve dispatch record for an order."""
        ...

    def list_all(self) -> list[Dispatch]:
        """List all dispatch records."""
        ...


class ApprovalRepository(Protocol):
    """Port for approval workflow state persistence and retrieval."""

    def save(self, *, approval: Approval) -> None:
        """Save or update an approval record."""
        ...

    def get_by_id(self, *, approval_id: UUID) -> Approval | None:
        """Retrieve approval by ID."""
        ...

    def get_by_snapshot_version(self, *, snapshot_version: str) -> Approval | None:
        """Retrieve approval bound to a specific snapshot version."""
        ...


class HandoffRepository(Protocol):
    """Port for human handoff case persistence and retrieval."""

    def save(self, *, handoff_case: HandoffCase) -> None:
        """Save or update a handoff case."""
        ...

    def get_by_id(self, *, handoff_id: UUID) -> HandoffCase | None:
        """Retrieve handoff case by ID."""
        ...

    def list_by_run(self, *, run_id: UUID) -> list[HandoffCase]:
        """List handoff cases created for a run."""
        ...

    def list_all(self) -> list[HandoffCase]:
        """List all handoff cases."""
        ...


class ToolExecutionRepository(Protocol):
    """Port for tool execution persistence and retrieval."""

    def save(self, *, execution: ToolExecution) -> None:
        """Save or update a tool execution record."""
        ...

    def get_by_id(self, *, execution_id: UUID) -> ToolExecution | None:
        """Retrieve tool execution by ID."""
        ...

    def get_by_idempotency_key(self, *, idempotency_key: str) -> ToolExecution | None:
        """Retrieve tool execution by idempotency key."""
        ...

    def list_by_run(self, *, run_id: UUID) -> list[ToolExecution]:
        """List tool executions for a run."""
        ...


class VerificationRepository(Protocol):
    """Port for verification outcome persistence and retrieval."""

    def save(self, *, verification: Verification) -> None:
        """Save or update a verification record."""
        ...

    def get_by_id(self, *, verification_id: UUID) -> Verification | None:
        """Retrieve verification by ID."""
        ...

    def get_by_execution_id(self, *, execution_id: UUID) -> Verification | None:
        """Retrieve verification associated with a tool execution."""
        ...

    def list_by_run(self, *, run_id: UUID) -> list[Verification]:
        """List verifications for a run."""
        ...
