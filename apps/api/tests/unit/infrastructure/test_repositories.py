from datetime import date
from decimal import Decimal
from uuid import uuid4

from vaaniflow.domain.models.customer import CustomerStatus
from vaaniflow.domain.models.quote import QuoteStatus
from vaaniflow.domain.schemas.semantic import TaxTreatment
from vaaniflow.infrastructure.repositories import (
    SyntheticRepositories,
)
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    CUST_SHARMA_BUILDTECH_ID,
    PROD_ACC_CEMENT_ID,
    PROD_ULTRATECH_CEMENT_ID,
    QUOTE_SHARMA_ACC_EXPIRED_ID,
    QUOTE_SHARMA_ULTRATECH_VALID_ID,
    WH_PEENYA_ID,
)


def test_customer_repository_lookup_and_search() -> None:
    repos = SyntheticRepositories()

    # Exact ID lookup
    cust = repos.customers.get_by_id(customer_id=CUST_SHARMA_BUILDERS_ID)
    assert cust is not None
    assert cust.name == "Sharma Builders"
    assert cust.status == CustomerStatus.ACTIVE

    # Non-existent ID
    assert repos.customers.get_by_id(customer_id=uuid4()) is None

    # Search with alias
    by_alias = repos.customers.search(query="sharma construction")
    assert len(by_alias) == 1
    assert by_alias[0].customer_id == CUST_SHARMA_BUILDERS_ID

    # Deliberate ambiguity: "sharma" matches both Sharma Builders and Sharma Buildtech
    ambiguous = repos.customers.search(query="sharma")
    assert len(ambiguous) == 2
    matched_ids = {c.customer_id for c in ambiguous}
    assert CUST_SHARMA_BUILDERS_ID in matched_ids
    assert CUST_SHARMA_BUILDTECH_ID in matched_ids


def test_product_repository_lookup_and_sku() -> None:
    repos = SyntheticRepositories()

    # Lookup by ID
    prod = repos.products.get_by_id(product_id=PROD_ULTRATECH_CEMENT_ID)
    assert prod is not None
    assert prod.sku == "CEM-UT-001"
    assert prod.unit == "bag"

    # Lookup by SKU
    prod_by_sku = repos.products.get_by_sku(sku="cem-ut-001")
    assert prod_by_sku is not None
    assert prod_by_sku.product_id == PROD_ULTRATECH_CEMENT_ID

    # Ambiguity check: "ultratech cement" matches both regular and super cement
    matches = repos.products.search(query="ultratech cement")
    assert len(matches) >= 2
    sku_set = {p.sku for p in matches}
    assert "CEM-UT-001" in sku_set
    assert "CEM-UT-002" in sku_set


def test_quote_repository_and_historical_pricing() -> None:
    repos = SyntheticRepositories()

    # Find canonical active quote for Sharma Builders on UltraTech cement
    quotes = repos.quotes.find_quotes(
        customer_id=CUST_SHARMA_BUILDERS_ID,
        product_id=PROD_ULTRATECH_CEMENT_ID,
        status=QuoteStatus.VALID,
    )
    assert len(quotes) == 1
    canonical_quote = quotes[0]
    assert canonical_quote.quote_id == QUOTE_SHARMA_ULTRATECH_VALID_ID
    assert canonical_quote.unit_price == Decimal("420.00")
    assert canonical_quote.currency == "INR"
    assert canonical_quote.quoted_on == date(2026, 10, 15)

    # Valid as of Oct 18, 2026
    as_of_quotes = repos.quotes.find_quotes(
        customer_id=CUST_SHARMA_BUILDERS_ID,
        as_of_date=date(2026, 10, 18),
    )
    assert len(as_of_quotes) == 1
    assert as_of_quotes[0].product_id == PROD_ULTRATECH_CEMENT_ID

    # Expired quote verification
    expired = repos.quotes.get_by_id(quote_id=QUOTE_SHARMA_ACC_EXPIRED_ID)
    assert expired is not None
    assert expired.status == QuoteStatus.EXPIRED
    assert expired.unit_price == Decimal("390.00")


def test_inventory_repository_and_stock_levels() -> None:
    repos = SyntheticRepositories()

    # UltraTech stock in Peenya warehouse
    stock = repos.inventory.get_by_product(
        product_id=PROD_ULTRATECH_CEMENT_ID,
        warehouse_id=WH_PEENYA_ID,
    )
    assert len(stock) == 1
    assert stock[0].available_quantity == 500
    assert stock[0].reserved_quantity == 50
    # Net available is 450
    assert stock[0].available_quantity - stock[0].reserved_quantity == 450

    # Shortage fixture check (Scenario E: ACC cement has only 120 bags)
    acc_stock = repos.inventory.get_by_product(product_id=PROD_ACC_CEMENT_ID)
    assert len(acc_stock) == 1
    assert acc_stock[0].available_quantity == 120


def test_warehouse_repository() -> None:
    repos = SyntheticRepositories()

    wh = repos.warehouses.get_by_code(code="WH-PEENYA-01")
    assert wh is not None
    assert wh.warehouse_id == WH_PEENYA_ID
    assert wh.city == "Bengaluru"


def test_tax_rules_and_deterministic_calculation() -> None:
    repos = SyntheticRepositories()

    rule = repos.tax_rules.get_rule(category="CEMENT", jurisdiction="KA")
    assert rule is not None
    assert rule.category == "CEMENT"
    assert rule.components["CGST"] == Decimal("0.14")
    assert rule.components["SGST"] == Decimal("0.14")

    # Canonical scenario: 200 bags * 420 = ₹84,000 taxable amount
    taxable_amount = Decimal("84000.00")
    calc = rule.calculate(taxable_amount=taxable_amount, treatment=TaxTreatment.EXCLUSIVE)

    assert calc.taxable_amount == Decimal("84000.00")
    assert len(calc.components) == 2
    comp_map = {c.name: c.amount for c in calc.components}
    assert comp_map["CGST"] == Decimal("11760.00")
    assert comp_map["SGST"] == Decimal("11760.00")
    assert calc.total_tax == Decimal("23520.00")
    assert calc.total_amount == Decimal("107520.00")
    assert calc.treatment == TaxTreatment.EXCLUSIVE
    assert "GST-2026-KA-CEM" in calc.provenance

    # Test inclusive calculation
    calc_inc = rule.calculate(taxable_amount=Decimal("128.00"), treatment=TaxTreatment.INCLUSIVE)
    assert calc_inc.taxable_amount == Decimal("100.00")
    assert calc_inc.total_tax == Decimal("28.00")
    assert calc_inc.total_amount == Decimal("128.00")
