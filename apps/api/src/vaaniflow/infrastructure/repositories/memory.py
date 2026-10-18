from __future__ import annotations

from datetime import date
from uuid import UUID

from vaaniflow.application.ports.business_data import (
    CustomerRepository,
    InventoryRepository,
    ProductRepository,
    QuoteRepository,
    TaxRuleRepository,
    WarehouseRepository,
)
from vaaniflow.domain.models.customer import Customer, CustomerStatus
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.models.product import Product, ProductStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tax import TaxRule
from vaaniflow.domain.models.warehouse import Warehouse


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
