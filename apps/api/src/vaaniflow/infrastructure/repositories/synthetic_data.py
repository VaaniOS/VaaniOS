from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from vaaniflow.domain.models.customer import Customer, CustomerStatus
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.models.product import Product, ProductStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tax import TaxRule
from vaaniflow.domain.models.warehouse import Warehouse
from vaaniflow.infrastructure.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryInventoryRepository,
    InMemoryProductRepository,
    InMemoryQuoteRepository,
    InMemoryTaxRuleRepository,
    InMemoryWarehouseRepository,
)

# Reference timestamp for synthetic records
_NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)

# Deterministic UUIDs
CUST_SHARMA_BUILDERS_ID = UUID("00000000-0000-4000-8000-000000000001")
CUST_SHARMA_BUILDTECH_ID = UUID("00000000-0000-4000-8000-000000000002")
CUST_KUMAR_CONSTRUCTIONS_ID = UUID("00000000-0000-4000-8000-000000000003")
CUST_PEENYA_INFRA_ID = UUID("00000000-0000-4000-8000-000000000004")

WH_PEENYA_ID = UUID("00000000-0000-4000-8000-000000000010")

PROD_ULTRATECH_CEMENT_ID = UUID("00000000-0000-4000-8000-000000000020")
PROD_ULTRATECH_SUPER_ID = UUID("00000000-0000-4000-8000-000000000021")
PROD_ACC_CEMENT_ID = UUID("00000000-0000-4000-8000-000000000022")
PROD_JSW_STEEL_ID = UUID("00000000-0000-4000-8000-000000000023")

QUOTE_SHARMA_ULTRATECH_VALID_ID = UUID("00000000-0000-4000-8000-000000000030")
QUOTE_SHARMA_ACC_EXPIRED_ID = UUID("00000000-0000-4000-8000-000000000031")

INV_ULTRATECH_ID = UUID("00000000-0000-4000-8000-000000000040")
INV_ULTRATECH_SUPER_ID = UUID("00000000-0000-4000-8000-000000000041")
INV_ACC_LOW_STOCK_ID = UUID("00000000-0000-4000-8000-000000000042")
INV_JSW_STEEL_ID = UUID("00000000-0000-4000-8000-000000000043")

TAX_CEMENT_KA_ID = UUID("00000000-0000-4000-8000-000000000050")
TAX_STEEL_KA_ID = UUID("00000000-0000-4000-8000-000000000051")


def get_synthetic_warehouses() -> list[Warehouse]:
    return [
        Warehouse(
            warehouse_id=WH_PEENYA_ID,
            code="WH-PEENYA-01",
            name="Peenya Main Warehouse",
            city="Bengaluru",
            state="Karnataka",
            address="Plot 42, 3rd Phase, Peenya Industrial Area, Bengaluru - 560058",
            is_active=True,
        )
    ]


def get_synthetic_customers() -> list[Customer]:
    return [
        Customer(
            customer_id=CUST_SHARMA_BUILDERS_ID,
            name="Sharma Builders",
            aliases=["sharma builders", "sharma", "sharma construction"],
            phone="+919876543210",
            email="orders@sharmabuilders.in",
            address="Site 12, Outer Ring Road, Peenya",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560058",
            tax_id="29ABCDE1234F1Z5",
            status=CustomerStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        # Deliberate ambiguity fixture: another "Sharma" customer in Bangalore
        Customer(
            customer_id=CUST_SHARMA_BUILDTECH_ID,
            name="Sharma Buildtech",
            aliases=["sharma buildtech", "sharma"],
            phone="+919876543211",
            email="contact@sharmabuildtech.com",
            address="Shop 5, Peenya 2nd Stage",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560058",
            tax_id="29FGHIJ5678K1Z2",
            status=CustomerStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        Customer(
            customer_id=CUST_KUMAR_CONSTRUCTIONS_ID,
            name="Kumar Constructions",
            aliases=["kumar constructions", "kumar builders", "kumar"],
            phone="+919876543212",
            email="purchase@kumarconstructions.com",
            address="No. 88, Yeshwanthpur Industrial Suburb",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560022",
            tax_id="29KLMNO9012P1Z9",
            status=CustomerStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        Customer(
            customer_id=CUST_PEENYA_INFRA_ID,
            name="Peenya Infra Works",
            aliases=["peenya infra works", "peenya infra"],
            phone="+919876543213",
            email="info@peenyainfra.in",
            address="Plot 105, 4th Phase, Peenya",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560058",
            tax_id="29PQRST3456U1Z4",
            status=CustomerStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    ]


def get_synthetic_products() -> list[Product]:
    return [
        Product(
            product_id=PROD_ULTRATECH_CEMENT_ID,
            sku="CEM-UT-001",
            name="UltraTech Cement 50kg Bag",
            brand="UltraTech",
            product_family="Cement",
            category="Building Materials",
            aliases=["ultratech cement", "ultratech", "ut cement"],
            unit="bag",
            packaging="50kg HDPE bag",
            status=ProductStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        # Deliberate ambiguity fixture: another UltraTech cement variant
        Product(
            product_id=PROD_ULTRATECH_SUPER_ID,
            sku="CEM-UT-002",
            name="UltraTech Super Cement 50kg Bag",
            brand="UltraTech",
            product_family="Cement",
            category="Building Materials",
            aliases=["ultratech super cement", "ultratech super", "super cement"],
            unit="bag",
            packaging="50kg Paper bag",
            status=ProductStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        Product(
            product_id=PROD_ACC_CEMENT_ID,
            sku="CEM-ACC-001",
            name="ACC Cement 50kg Bag",
            brand="ACC",
            product_family="Cement",
            category="Building Materials",
            aliases=["acc cement", "acc"],
            unit="bag",
            packaging="50kg HDPE bag",
            status=ProductStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        Product(
            product_id=PROD_JSW_STEEL_ID,
            sku="STL-JSW-001",
            name="JSW Steel 12mm TMT Bar",
            brand="JSW",
            product_family="Steel",
            category="TMT Rebars",
            aliases=["jsw steel", "steel", "tmt bar", "12mm tmt"],
            unit="tonne",
            packaging="Bundles",
            status=ProductStatus.ACTIVE,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    ]


def get_synthetic_quotes() -> list[Quote]:
    return [
        # Canonical quote for Ramesh scenario: ₹420/bag for Sharma Builders on UltraTech cement
        Quote(
            quote_id=QUOTE_SHARMA_ULTRATECH_VALID_ID,
            customer_id=CUST_SHARMA_BUILDERS_ID,
            product_id=PROD_ULTRATECH_CEMENT_ID,
            unit="bag",
            unit_price=Decimal("420.00"),
            currency="INR",
            quoted_on=date(2026, 10, 15),
            valid_until=date(2026, 11, 15),
            status=QuoteStatus.VALID,
            customer_specific=True,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        # Expired quote fixture for Scenario D testing
        Quote(
            quote_id=QUOTE_SHARMA_ACC_EXPIRED_ID,
            customer_id=CUST_SHARMA_BUILDERS_ID,
            product_id=PROD_ACC_CEMENT_ID,
            unit="bag",
            unit_price=Decimal("390.00"),
            currency="INR",
            quoted_on=date(2026, 8, 1),
            valid_until=date(2026, 9, 1),
            status=QuoteStatus.EXPIRED,
            customer_specific=True,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    ]


def get_synthetic_inventories() -> list[Inventory]:
    return [
        # Ample stock for canonical happy path (200 bags requested, 450 net available)
        Inventory(
            inventory_id=INV_ULTRATECH_ID,
            product_id=PROD_ULTRATECH_CEMENT_ID,
            warehouse_id=WH_PEENYA_ID,
            available_quantity=500,
            reserved_quantity=50,
            updated_at=_NOW,
        ),
        Inventory(
            inventory_id=INV_ULTRATECH_SUPER_ID,
            product_id=PROD_ULTRATECH_SUPER_ID,
            warehouse_id=WH_PEENYA_ID,
            available_quantity=200,
            reserved_quantity=0,
            updated_at=_NOW,
        ),
        # Low stock shortage fixture for Scenario E testing (only 120 bags available)
        Inventory(
            inventory_id=INV_ACC_LOW_STOCK_ID,
            product_id=PROD_ACC_CEMENT_ID,
            warehouse_id=WH_PEENYA_ID,
            available_quantity=120,
            reserved_quantity=0,
            updated_at=_NOW,
        ),
        Inventory(
            inventory_id=INV_JSW_STEEL_ID,
            product_id=PROD_JSW_STEEL_ID,
            warehouse_id=WH_PEENYA_ID,
            available_quantity=50,
            reserved_quantity=5,
            updated_at=_NOW,
        ),
    ]


def get_synthetic_tax_rules() -> list[TaxRule]:
    return [
        # Cement in Karnataka: 28% GST (14% CGST + 14% SGST)
        TaxRule(
            rule_id=TAX_CEMENT_KA_ID,
            category="CEMENT",
            jurisdiction="KA",
            components={"CGST": Decimal("0.14"), "SGST": Decimal("0.14")},
            version="GST-2026-KA-CEM",
            effective_from=date(2026, 1, 1),
        ),
        # Steel in Karnataka: 18% GST (9% CGST + 9% SGST)
        TaxRule(
            rule_id=TAX_STEEL_KA_ID,
            category="STEEL",
            jurisdiction="KA",
            components={"CGST": Decimal("0.09"), "SGST": Decimal("0.09")},
            version="GST-2026-KA-STL",
            effective_from=date(2026, 1, 1),
        ),
    ]


class SyntheticRepositories:
    """Convenience bundle of pre-seeded in-memory business repositories."""

    def __init__(self) -> None:
        self.warehouses = InMemoryWarehouseRepository(get_synthetic_warehouses())
        self.customers = InMemoryCustomerRepository(get_synthetic_customers())
        self.products = InMemoryProductRepository(get_synthetic_products())
        self.quotes = InMemoryQuoteRepository(get_synthetic_quotes())
        self.inventory = InMemoryInventoryRepository(get_synthetic_inventories())
        self.tax_rules = InMemoryTaxRuleRepository(get_synthetic_tax_rules())
