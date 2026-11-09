from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from vaaniflow.application.ports.business_data import (
    ApprovalRepository,
    CustomerRepository,
    DispatchRepository,
    HandoffRepository,
    InventoryRepository,
    InvoiceRepository,
    OrderRepository,
    ProductRepository,
    QuoteRepository,
    TaxRuleRepository,
    ToolExecutionRepository,
    TraceRepository,
    VerificationRepository,
    VoiceRunRepository,
    WarehouseRepository,
)
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
from vaaniflow.domain.models.voice_run import VoiceRun
from vaaniflow.domain.models.warehouse import Warehouse
from vaaniflow.traces.models import RunTrace, TraceEvent

if TYPE_CHECKING:
    from vaaniflow.execution.plan import PendingExecution


class InMemoryCustomerRepository(CustomerRepository):
    """In-memory implementation of CustomerRepository for testing and mock execution."""

    def __init__(self, customers: list[Customer] | None = None) -> None:
        self._customers: dict[UUID, Customer] = {c.customer_id: c for c in (customers or [])}

    def add(self, customer: Customer) -> None:
        self._customers[customer.customer_id] = customer

    def get_by_id(self, *, customer_id: UUID) -> Customer | None:
        return self._customers.get(customer_id)

    def search(
        self,
        *,
        query: str,
        status: CustomerStatus | None = CustomerStatus.ACTIVE,
    ) -> list[Customer]:
        q = query.strip().lower()
        if not q:
            return []

        matches: list[Customer] = []
        for customer in self._customers.values():
            if status is not None and customer.status != status:
                continue

            # Check exact or substring match in name, aliases, phone, tax_id
            name_lower = customer.name.lower()
            aliases_lower = [a.lower() for a in customer.aliases]
            phone = customer.phone or ""
            tax_id = (customer.tax_id or "").lower()

            if q in name_lower or any(q in a for a in aliases_lower) or q == phone or q == tax_id:
                matches.append(customer)

        return matches

    def list_all(self) -> list[Customer]:
        return list(self._customers.values())


class InMemoryProductRepository(ProductRepository):
    """In-memory implementation of ProductRepository."""

    def __init__(self, products: list[Product] | None = None) -> None:
        self._products: dict[UUID, Product] = {p.product_id: p for p in (products or [])}

    def add(self, product: Product) -> None:
        self._products[product.product_id] = product

    def get_by_id(self, *, product_id: UUID) -> Product | None:
        return self._products.get(product_id)

    def get_by_sku(self, *, sku: str) -> Product | None:
        sku_clean = sku.strip().upper()
        for product in self._products.values():
            if product.sku.upper() == sku_clean:
                return product
        return None

    def search(
        self,
        *,
        query: str,
        status: ProductStatus | None = ProductStatus.ACTIVE,
    ) -> list[Product]:
        q = query.strip().lower()
        if not q:
            return []

        matches: list[Product] = []
        for product in self._products.values():
            if status is not None and product.status != status:
                continue

            name_lower = product.name.lower()
            sku_lower = product.sku.lower()
            brand_lower = (product.brand or "").lower()
            family_lower = (product.product_family or "").lower()
            aliases_lower = [a.lower() for a in product.aliases]

            if (
                q in name_lower
                or q in sku_lower
                or (brand_lower and q in brand_lower)
                or (family_lower and q in family_lower)
                or any(q in a for a in aliases_lower)
            ):
                matches.append(product)

        return matches

    def list_all(self) -> list[Product]:
        return list(self._products.values())


class InMemoryQuoteRepository(QuoteRepository):
    """In-memory implementation of QuoteRepository."""

    def __init__(self, quotes: list[Quote] | None = None) -> None:
        self._quotes: dict[UUID, Quote] = {q.quote_id: q for q in (quotes or [])}

    def add(self, quote: Quote) -> None:
        self._quotes[quote.quote_id] = quote

    def get_by_id(self, *, quote_id: UUID) -> Quote | None:
        return self._quotes.get(quote_id)

    def find_quotes(
        self,
        *,
        customer_id: UUID | None = None,
        product_id: UUID | None = None,
        status: QuoteStatus | None = None,
        quoted_on: date | None = None,
        as_of_date: date | None = None,
    ) -> list[Quote]:
        results: list[Quote] = []
        for quote in self._quotes.values():
            if customer_id is not None and quote.customer_id != customer_id:
                continue
            if product_id is not None and quote.product_id != product_id:
                continue
            if status is not None and quote.status != status:
                continue
            if quoted_on is not None and quote.quoted_on != quoted_on:
                continue
            if as_of_date is not None:
                # Must be quoted on or before as_of_date, and not expired by as_of_date
                if quote.quoted_on > as_of_date:
                    continue
                if quote.valid_until is not None and quote.valid_until < as_of_date:
                    continue

            results.append(quote)

        return results

    def list_all(self) -> list[Quote]:
        return list(self._quotes.values())


class InMemoryInventoryRepository(InventoryRepository):
    """In-memory implementation of InventoryRepository."""

    def __init__(self, inventories: list[Inventory] | None = None) -> None:
        self._inventories: dict[UUID, Inventory] = {i.inventory_id: i for i in (inventories or [])}

    def add(self, inventory: Inventory) -> None:
        self._inventories[inventory.inventory_id] = inventory

    def get_by_id(self, *, inventory_id: UUID) -> Inventory | None:
        return self._inventories.get(inventory_id)

    def get_by_product(
        self,
        *,
        product_id: UUID,
        warehouse_id: UUID | None = None,
    ) -> list[Inventory]:
        results: list[Inventory] = []
        for inv in self._inventories.values():
            if inv.product_id == product_id and (
                warehouse_id is None or inv.warehouse_id == warehouse_id
            ):
                results.append(inv)
        return results

    def list_all(self) -> list[Inventory]:
        return list(self._inventories.values())


class InMemoryWarehouseRepository(WarehouseRepository):
    """In-memory implementation of WarehouseRepository."""

    def __init__(self, warehouses: list[Warehouse] | None = None) -> None:
        self._warehouses: dict[UUID, Warehouse] = {w.warehouse_id: w for w in (warehouses or [])}

    def add(self, warehouse: Warehouse) -> None:
        self._warehouses[warehouse.warehouse_id] = warehouse

    def get_by_id(self, *, warehouse_id: UUID) -> Warehouse | None:
        return self._warehouses.get(warehouse_id)

    def get_by_code(self, *, code: str) -> Warehouse | None:
        code_clean = code.strip().upper()
        for wh in self._warehouses.values():
            if wh.code.upper() == code_clean:
                return wh
        return None

    def list_all(self) -> list[Warehouse]:
        return list(self._warehouses.values())


class InMemoryTaxRuleRepository(TaxRuleRepository):
    """In-memory implementation of TaxRuleRepository."""

    def __init__(self, rules: list[TaxRule] | None = None) -> None:
        self._rules: dict[UUID, TaxRule] = {r.rule_id: r for r in (rules or [])}

    def add(self, rule: TaxRule) -> None:
        self._rules[rule.rule_id] = rule

    def get_rule(
        self,
        *,
        category: str,
        jurisdiction: str = "KA",
        as_of_date: date | None = None,
    ) -> TaxRule | None:
        cat_clean = category.strip().upper()
        jur_clean = jurisdiction.strip().upper()

        for rule in self._rules.values():
            if rule.category.upper() == cat_clean and rule.jurisdiction.upper() == jur_clean:
                if as_of_date is not None:
                    if rule.effective_from is not None and rule.effective_from > as_of_date:
                        continue
                    if rule.effective_until is not None and rule.effective_until < as_of_date:
                        continue
                return rule
        return None

    def list_all(self) -> list[TaxRule]:
        return list(self._rules.values())


class InMemoryOrderRepository(OrderRepository):
    """In-memory implementation of OrderRepository."""

    def __init__(self, orders: list[Order] | None = None) -> None:
        self._orders: dict[UUID, Order] = {o.order_id: o for o in (orders or [])}

    def save(self, *, order: Order) -> None:
        self._orders[order.order_id] = order

    def get_by_id(self, *, order_id: UUID) -> Order | None:
        return self._orders.get(order_id)

    def list_by_customer(self, *, customer_id: UUID) -> list[Order]:
        return [o for o in self._orders.values() if o.customer_id == customer_id]

    def list_all(self) -> list[Order]:
        return list(self._orders.values())


class InMemoryInvoiceRepository(InvoiceRepository):
    """In-memory implementation of InvoiceRepository."""

    def __init__(self, invoices: list[Invoice] | None = None) -> None:
        self._invoices: dict[UUID, Invoice] = {i.invoice_id: i for i in (invoices or [])}

    def save(self, *, invoice: Invoice) -> None:
        self._invoices[invoice.invoice_id] = invoice

    def get_by_id(self, *, invoice_id: UUID) -> Invoice | None:
        return self._invoices.get(invoice_id)

    def get_by_order_id(self, *, order_id: UUID) -> Invoice | None:
        for inv in self._invoices.values():
            if inv.order_id == order_id:
                return inv
        return None

    def list_all(self) -> list[Invoice]:
        return list(self._invoices.values())


class InMemoryDispatchRepository(DispatchRepository):
    """In-memory implementation of DispatchRepository."""

    def __init__(self, dispatches: list[Dispatch] | None = None) -> None:
        self._dispatches: dict[UUID, Dispatch] = {d.dispatch_id: d for d in (dispatches or [])}

    def save(self, *, dispatch: Dispatch) -> None:
        self._dispatches[dispatch.dispatch_id] = dispatch

    def get_by_id(self, *, dispatch_id: UUID) -> Dispatch | None:
        return self._dispatches.get(dispatch_id)

    def get_by_order_id(self, *, order_id: UUID) -> Dispatch | None:
        for disp in self._dispatches.values():
            if disp.order_id == order_id:
                return disp
        return None

    def list_all(self) -> list[Dispatch]:
        return list(self._dispatches.values())


class InMemoryApprovalRepository(ApprovalRepository):
    """In-memory implementation of ApprovalRepository."""

    def __init__(self, approvals: list[Approval] | None = None) -> None:
        self._approvals: dict[UUID, Approval] = {a.approval_id: a for a in (approvals or [])}

    def save(self, *, approval: Approval) -> None:
        self._approvals[approval.approval_id] = approval

    def get_by_id(self, *, approval_id: UUID) -> Approval | None:
        return self._approvals.get(approval_id)

    def get_by_snapshot_version(self, *, snapshot_version: str) -> Approval | None:
        for app in self._approvals.values():
            if app.snapshot_version == snapshot_version:
                return app
        return None


class InMemoryHandoffRepository(HandoffRepository):
    """In-memory implementation of HandoffRepository."""

    def __init__(self, cases: list[HandoffCase] | None = None) -> None:
        self._cases: dict[UUID, HandoffCase] = {c.handoff_id: c for c in (cases or [])}

    def save(self, *, handoff_case: HandoffCase) -> None:
        self._cases[handoff_case.handoff_id] = handoff_case

    def get_by_id(self, *, handoff_id: UUID) -> HandoffCase | None:
        return self._cases.get(handoff_id)

    def list_by_run(self, *, run_id: UUID) -> list[HandoffCase]:
        return [c for c in self._cases.values() if c.run_id == run_id]

    def list_all(self) -> list[HandoffCase]:
        return list(self._cases.values())


class InMemoryToolExecutionRepository(ToolExecutionRepository):
    """In-memory implementation of ToolExecutionRepository."""

    def __init__(self, executions: list[ToolExecution] | None = None) -> None:
        self._executions: dict[UUID, ToolExecution] = {
            e.execution_id: e for e in (executions or [])
        }

    def save(self, *, execution: ToolExecution) -> None:
        self._executions[execution.execution_id] = execution

    def get_by_id(self, *, execution_id: UUID) -> ToolExecution | None:
        return self._executions.get(execution_id)

    def get_by_idempotency_key(self, *, idempotency_key: str) -> ToolExecution | None:
        for ex in self._executions.values():
            if ex.idempotency_key == idempotency_key:
                return ex
        return None

    def list_by_run(self, *, run_id: UUID) -> list[ToolExecution]:
        return [e for e in self._executions.values() if e.run_id == run_id]


class InMemoryVerificationRepository(VerificationRepository):
    """In-memory implementation of VerificationRepository."""

    def __init__(self, verifications: list[Verification] | None = None) -> None:
        self._verifications: dict[UUID, Verification] = {
            v.verification_id: v for v in (verifications or [])
        }

    def save(self, *, verification: Verification) -> None:
        self._verifications[verification.verification_id] = verification

    def get_by_id(self, *, verification_id: UUID) -> Verification | None:
        return self._verifications.get(verification_id)

    def get_by_execution_id(self, *, execution_id: UUID) -> Verification | None:
        for v in self._verifications.values():
            if v.execution_id == execution_id:
                return v
        return None

    def list_by_run(self, *, run_id: UUID) -> list[Verification]:
        return [v for v in self._verifications.values() if v.run_id == run_id]


class InMemoryVoiceRunRepository(VoiceRunRepository):
    """In-memory implementation of VoiceRunRepository."""

    def __init__(self, runs: list[VoiceRun] | None = None) -> None:
        self._runs: dict[UUID, VoiceRun] = {r.run_id: r for r in (runs or [])}

    def save(self, *, run: VoiceRun) -> None:
        self._runs[run.run_id] = run

    def get_by_id(self, *, run_id: UUID) -> VoiceRun | None:
        return self._runs.get(run_id)

    def list_all(self) -> list[VoiceRun]:
        return list(self._runs.values())


class InMemoryTraceRepository(TraceRepository):
    """In-memory implementation of TraceRepository."""

    def __init__(self) -> None:
        self._events_by_run: dict[UUID, list[TraceEvent]] = {}

    def record_event(self, *, event: TraceEvent) -> None:
        if event.run_id not in self._events_by_run:
            self._events_by_run[event.run_id] = []
        self._events_by_run[event.run_id].append(event)

    def get_trace(self, *, run_id: UUID) -> RunTrace | None:
        events = self._events_by_run.get(run_id)
        if not events:
            return None

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        started_at = sorted_events[0].timestamp
        completed_at = sorted_events[-1].timestamp if len(sorted_events) > 1 else None
        total_latency = sum(e.latency_ms or 0 for e in sorted_events)

        return RunTrace(
            run_id=run_id,
            events=sorted_events,
            total_latency_ms=total_latency,
            started_at=started_at,
            completed_at=completed_at,
        )

    def list_all_traces(self) -> list[RunTrace]:
        traces: list[RunTrace] = []
        for run_id in self._events_by_run:
            trace = self.get_trace(run_id=run_id)
            if trace is not None:
                traces.append(trace)
        return traces


class InMemoryPendingExecutionRepository:
    """Stores execution plans awaiting approval, keyed by their approval id."""

    def __init__(self) -> None:
        self._pending: dict[UUID, PendingExecution] = {}

    def save(self, *, pending: PendingExecution) -> None:
        self._pending[pending.approval_id] = pending

    def get_by_approval_id(self, *, approval_id: UUID) -> PendingExecution | None:
        return self._pending.get(approval_id)

    def list_by_run(self, *, run_id: UUID) -> list[PendingExecution]:
        return [p for p in self._pending.values() if p.plan.run_id == run_id]
