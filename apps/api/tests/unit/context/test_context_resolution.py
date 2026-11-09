from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from vaaniflow.context.models.business_context import (
    ResolvedCustomer,
    ResolvedProduct,
)
from vaaniflow.context.models.resolution import ResolutionStatus
from vaaniflow.context.resolvers.customer import CustomerResolver
from vaaniflow.context.resolvers.inventory import InventoryResolver
from vaaniflow.context.resolvers.product import ProductResolver
from vaaniflow.context.resolvers.quote import PriceQuoteResolver
from vaaniflow.context.resolvers.temporal import TemporalResolver
from vaaniflow.context.service import ContextResolutionService
from vaaniflow.domain.models.customer import Customer
from vaaniflow.domain.models.product import Product
from vaaniflow.domain.models.quote import QuoteStatus
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    PriceSource,
    ReferenceType,
    SemanticEntity,
    SemanticEntityType,
    SemanticPrice,
    SemanticQuantity,
    SemanticReference,
    SemanticSlot,
    SemanticState,
    TaxTreatment,
    TemporalDirection,
    TemporalExpression,
    TemporalKind,
    TemporalResolutionStatus,
    TextSpan,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.infrastructure.repositories import SyntheticRepositories
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    PROD_ACC_CEMENT_ID,
    PROD_ULTRATECH_CEMENT_ID,
    QUOTE_SHARMA_ULTRATECH_VALID_ID,
)
from vaaniflow.semantic.compiler import SemanticCompiler

FIXED_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

CANONICAL_VOICE_NOTE = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)


def _compile(text: str) -> SemanticState:
    transcript = Transcript(
        transcript_id=uuid4(),
        provider="test",
        language="en-IN",
        text=text,
        created_at=FIXED_TIME,
    )
    return SemanticCompiler(clock=lambda: FIXED_TIME).compile(transcript)


def test_canonical_scenario_full_context_resolution() -> None:
    repos = SyntheticRepositories()
    service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
        timezone_str="Asia/Kolkata",
    )

    semantic_state = _compile(CANONICAL_VOICE_NOTE)
    run_id = uuid4()

    output = service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    assert output.is_fully_resolved is True
    assert output.has_ambiguities is False
    ctx = output.business_context

    # 1. Customer
    assert ctx.customer is not None
    assert ctx.customer.customer.customer_id == CUST_SHARMA_BUILDERS_ID
    assert ctx.customer.customer.name == "Sharma Builders"

    # 2. Product
    assert len(ctx.products) == 1
    assert ctx.products[0].product.product_id == PROD_ULTRATECH_CEMENT_ID
    assert ctx.products[0].product.sku == "CEM-UT-001"

    # 3. Quote and Price
    assert len(ctx.quotes) == 1
    assert ctx.quotes[0].quote.quote_id == QUOTE_SHARMA_ULTRATECH_VALID_ID
    assert ctx.quotes[0].quote.unit_price == Decimal("420.00")

    assert ctx.resolved_price is not None
    assert ctx.resolved_price.unit_price == Decimal("420.00")
    assert ctx.resolved_price.source_quote_id == QUOTE_SHARMA_ULTRATECH_VALID_ID
    assert ctx.resolved_price.currency == "INR"

    # 4. Inventory
    assert len(ctx.inventory) == 1
    assert ctx.inventory[0].inventory.available_quantity == 500
    assert ctx.inventory[0].inventory.reserved_quantity == 50

    # 5. Tax (28% GST on 200 * 420 = ₹84,000)
    assert output.tax_calculation is not None
    assert output.tax_calculation.taxable_amount == Decimal("84000.00")
    assert output.tax_calculation.total_tax == Decimal("23520.00")
    assert output.tax_calculation.total_amount == Decimal("107520.00")
    assert output.tax_calculation.treatment == TaxTreatment.EXCLUSIVE

    # 6. Snapshot audit verification
    assert output.snapshot["customer"]["customer"]["name"] == "Sharma Builders"
    assert output.snapshot["products"][0]["product"]["sku"] == "CEM-UT-001"
    assert output.snapshot["tax_calculation"]["total_amount"] == "107520.00"


def test_ambiguous_customer_scenario_c() -> None:
    repos = SyntheticRepositories()
    resolver = CustomerResolver(repos.customers)

    # Spoken customer is simply "sharma" -> matches Sharma Builders & Sharma Buildtech
    sem_cust = SemanticEntity(
        entity_id=uuid4(),
        entity_type=SemanticEntityType.CUSTOMER,
        surface_text="Sharma",
        normalized_text="sharma",
        span=TextSpan(start=0, end=6),
        confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
    )

    result, resolved_customer = resolver.resolve(
        semantic_customer=sem_cust,
        resolved_at=FIXED_TIME,
    )

    assert result.status == ResolutionStatus.AMBIGUOUS
    assert resolved_customer is None
    assert len(result.candidates) == 2
    names = {c.display_name for c in result.candidates}
    assert "Sharma Builders" in names
    assert "Sharma Buildtech" in names


def test_ambiguous_product_scenario_j() -> None:
    repos = SyntheticRepositories()
    resolver = ProductResolver(repos.products)

    # Spoken "cement" matches multiple catalog entries
    sem_prod = SemanticEntity(
        entity_id=uuid4(),
        entity_type=SemanticEntityType.PRODUCT,
        surface_text="cement",
        normalized_text="cement",
        span=TextSpan(start=0, end=6),
        confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
    )

    result, resolved_product = resolver.resolve(
        semantic_product=sem_prod,
        resolved_at=FIXED_TIME,
    )

    assert result.status == ResolutionStatus.AMBIGUOUS
    assert resolved_product is None
    assert len(result.candidates) >= 2


def test_stale_expired_quote_scenario_d() -> None:
    repos = SyntheticRepositories()
    resolver = PriceQuoteResolver(repos.quotes)

    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    customer = Customer(
        customer_id=CUST_SHARMA_BUILDERS_ID,
        name="Sharma Builders",
        created_at=now,
        updated_at=now,
    )
    product = Product(
        product_id=PROD_ACC_CEMENT_ID,
        sku="CEM-ACC-001",
        name="ACC Cement 50kg Bag",
        unit="bag",
        created_at=now,
        updated_at=now,
    )

    resolved_customer = ResolvedCustomer(customer=customer, resolution_id=uuid4(), resolved_at=now)
    resolved_product = ResolvedProduct(product=product, resolution_id=uuid4(), resolved_at=now)

    ref_id = uuid4()
    ref = SemanticReference(
        reference_id=ref_id,
        reference_type=ReferenceType.HISTORICAL_PRICE,
        target_slot=SemanticSlot.PRICE,
        surface_text="parso ka rate",
        normalized_text="parso ka rate",
        span=TextSpan(start=0, end=13),
        confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
    )
    pricing = SemanticPrice(
        price_id=uuid4(),
        source=PriceSource.HISTORICAL_REFERENCE,
        reference_id=ref_id,
        surface_text="parso ka rate",
        span=TextSpan(start=0, end=13),
        confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
    )

    result, resolved_quote, resolved_price = resolver.resolve(
        customer=resolved_customer,
        product=resolved_product,
        pricing=[pricing],
        references=[ref],
        resolved_date=date(2026, 8, 1),
        resolved_at=now,
    )

    # Safety check: Expired quotes must NOT be applied
    assert result.status == ResolutionStatus.INVALID
    assert resolved_quote is not None
    assert resolved_quote.quote.status == QuoteStatus.EXPIRED
    assert resolved_price is None
    assert "EXPIRED" in result.reason


def test_inventory_shortage_scenario_e() -> None:
    repos = SyntheticRepositories()
    resolver = InventoryResolver(repos.inventory)

    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    product = Product(
        product_id=PROD_ACC_CEMENT_ID,
        sku="CEM-ACC-001",
        name="ACC Cement 50kg Bag",
        unit="bag",
        created_at=now,
        updated_at=now,
    )
    resolved_prod = ResolvedProduct(product=product, resolution_id=uuid4(), resolved_at=now)

    # Request 500 bags of ACC cement (only 120 available in inventory)
    quantity = SemanticQuantity(
        value=Decimal(500),
        unit="bag",
        surface_text="500 bags",
        span=TextSpan(start=0, end=8),
        confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
    )

    result, inventories = resolver.resolve(
        product=resolved_prod,
        quantity=quantity,
        resolved_at=now,
    )

    assert result.status == ResolutionStatus.RESOLVED
    assert len(inventories) == 1
    assert inventories[0].inventory.available_quantity == 120
    # Shortage detected in evidence
    evidence_str = " ".join(result.candidates[0].evidence)
    assert "INVENTORY_SHORTAGE" in evidence_str


def test_temporal_parso_resolution() -> None:
    resolver = TemporalResolver(timezone_str="Asia/Kolkata")
    expr = TemporalExpression(
        expression_id=uuid4(),
        surface_text="parso",
        span=TextSpan(start=0, end=5),
        kind=TemporalKind.RELATIVE_DAY,
        normalized_expression="DAY_OFFSET:-2",
        direction=TemporalDirection.PAST,
        day_offset=-2,
        resolution_status=TemporalResolutionStatus.UNRESOLVED,
        confidence=Confidence(score=0.99, source=ConfidenceSource.RULE),
    )

    result, resolved_date = resolver.resolve(expression=expr, run_timestamp=FIXED_TIME)

    assert result.status == ResolutionStatus.RESOLVED
    assert resolved_date == date(2026, 10, 15)
