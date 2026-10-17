from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.context.models.business_context import (
    BusinessContext,
    ResolvedCustomer,
    ResolvedPrice,
)
from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.models.customer import Customer
from vaaniflow.domain.models.product import Product
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource


def test_resolved_customer_contract() -> None:
    now = datetime.now(UTC)

    customer = Customer(
        customer_id=uuid4(),
        name="Sharma Builders",
        aliases=["Sharma", "Sharma Construction"],
        phone="+919876543210",
        email="contact@sharmabuilders.example",
        address="Peenya Industrial Area",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        postal_code="560058",
        tax_id="29ABCDE1234F1Z5",
        created_at=now,
        updated_at=now,
    )

    resolution_id = uuid4()

    resolved = ResolvedCustomer(
        customer=customer,
        resolution_id=resolution_id,
        resolved_at=now,
    )

    assert resolved.customer.customer_id == customer.customer_id
    assert resolved.resolution_id == resolution_id
    assert resolved.resolved_at == now


def test_ambiguous_customer_resolution_contract() -> None:
    customer_id_a = uuid4()
    customer_id_b = uuid4()

    result = ResolutionResult(
        resolution_id=uuid4(),
        entity_type="customer",
        status=ResolutionStatus.AMBIGUOUS,
        query="Sharma",
        candidates=[
            ResolutionCandidate(
                candidate_id=uuid4(),
                entity_id=customer_id_a,
                display_name="Sharma Builders",
                confidence=Confidence(
                    score=0.82,
                    source=ConfidenceSource.MODEL,
                ),
                evidence=["Name similarity"],
            ),
            ResolutionCandidate(
                candidate_id=uuid4(),
                entity_id=customer_id_b,
                display_name="Sharma Hardware",
                confidence=Confidence(
                    score=0.79,
                    source=ConfidenceSource.MODEL,
                ),
                evidence=["Name similarity"],
            ),
        ],
        reason="Multiple high-confidence customer matches remain.",
    )

    assert result.status is ResolutionStatus.AMBIGUOUS
    assert result.selected_entity_id is None
    assert len(result.candidates) == 2


def test_resolved_quote_and_price_contract() -> None:
    now = datetime.now(UTC)

    customer_id = uuid4()
    product_id = uuid4()
    quote_id = uuid4()

    quote = Quote(
        quote_id=quote_id,
        customer_id=customer_id,
        product_id=product_id,
        status=QuoteStatus.VALID,
        unit="bag",
        unit_price=Decimal(420),
        currency="INR",
        quoted_on=date(2026, 10, 15),
        created_at=now,
        updated_at=now,
    )

    resolved_price = ResolvedPrice(
        product_id=product_id,
        customer_id=customer_id,
        unit="bag",
        unit_price=Decimal(420),
        currency="INR",
        source_quote_id=quote_id,
        resolved_on=date(2026, 10, 17),
    )

    assert quote.quote_id == quote_id
    assert quote.status is QuoteStatus.VALID
    assert quote.product_id == product_id
    assert quote.unit == "bag"
    assert quote.unit_price == Decimal(420)
    assert resolved_price.unit_price == Decimal(420)
    assert resolved_price.source_quote_id == quote_id


def test_resolved_price_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError):
        ResolvedPrice(
            product_id=uuid4(),
            customer_id=uuid4(),
            unit="bag",
            unit_price=Decimal(0),
            currency="INR",
            resolved_on=date(2026, 10, 17),
        )


def test_product_and_customer_resolution_are_separate() -> None:
    now = datetime.now(UTC)

    customer = Customer(
        customer_id=uuid4(),
        name="Sharma Builders",
        created_at=now,
        updated_at=now,
    )

    product = Product(
        product_id=uuid4(),
        sku="UTC-CEMENT-50KG",
        name="UltraTech Cement",
        aliases=["UltraTech"],
        unit="bag",
        created_at=now,
        updated_at=now,
    )

    customer_resolution = ResolvedCustomer(
        customer=customer,
        resolution_id=uuid4(),
        resolved_at=now,
    )

    product_resolution = ResolutionResult(
        resolution_id=uuid4(),
        entity_type="product",
        status=ResolutionStatus.RESOLVED,
        query="UltraTech cement",
        selected_entity_id=product.product_id,
        candidates=[
            ResolutionCandidate(
                candidate_id=uuid4(),
                entity_id=product.product_id,
                display_name=product.name,
                confidence=Confidence(
                    score=0.98,
                    source=ConfidenceSource.MODEL,
                ),
                evidence=["Exact product alias match"],
            )
        ],
        reason="Unique product match.",
    )

    assert customer_resolution.customer.customer_id != product.product_id
    assert product_resolution.selected_entity_id == product.product_id


def test_business_context_contract() -> None:
    now = datetime.now(UTC)

    customer = Customer(
        customer_id=uuid4(),
        name="Sharma Builders",
        created_at=now,
        updated_at=now,
    )

    resolved_customer = ResolvedCustomer(
        customer=customer,
        resolution_id=uuid4(),
        resolved_at=now,
    )

    context = BusinessContext(
        context_id=uuid4(),
        run_id=uuid4(),
        customer=resolved_customer,
        unresolved_references=[],
        resolution_errors=[],
        resolved_at=now,
    )

    assert context.customer is not None
    assert context.customer.customer.name == "Sharma Builders"
    assert context.unresolved_references == []
    assert context.resolution_errors == []
