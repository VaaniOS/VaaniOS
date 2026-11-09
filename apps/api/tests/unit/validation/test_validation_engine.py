from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from vaaniflow.context.service import ContextResolutionService
from vaaniflow.domain.models.validation import ValidationSeverity, ValidationStatus
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    SemanticQuantity,
    SemanticState,
    TextSpan,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.infrastructure.repositories import SyntheticRepositories
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.validation.engine import ValidationEngine

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


def test_canonical_scenario_validation_passes() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()

    semantic_state = _compile(CANONICAL_VOICE_NOTE)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    assert validation.status == ValidationStatus.PASSED
    check_map = {c.check_type: c for c in validation.checks}
    assert check_map["CUSTOMER_IDENTITY"].status == ValidationStatus.PASSED
    assert check_map["PRODUCT_IDENTITY"].status == ValidationStatus.PASSED
    assert check_map["INVENTORY_AVAILABILITY"].status == ValidationStatus.PASSED
    assert check_map["PRICE_RESOLVED"].status == ValidationStatus.PASSED
    assert check_map["QUOTE_VALIDITY"].status == ValidationStatus.PASSED
    assert check_map["TAX_CALCULATION"].status == ValidationStatus.PASSED


def test_suspicious_magnitude_scenario_b() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()

    # Scenario B: 200 -> 2000 bags ASR confusion
    note_2000 = (
        "Arre Suresh, Sharma Builders ko turant 2000 bag Ultratech cement dispatch karo. "
        "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
        "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
    )
    semantic_state = _compile(note_2000)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    # Must produce a warning due to magnitude
    assert validation.status in {ValidationStatus.WARNING, ValidationStatus.FAILED}
    check_map = {c.check_type: c for c in validation.checks}
    mag_check = check_map["QUANTITY_MAGNITUDE"]
    assert mag_check.status == ValidationStatus.WARNING
    assert mag_check.severity == ValidationSeverity.HIGH
    assert "unusually large" in mag_check.message


def test_missing_customer_fails_validation() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()

    # Note with no customer mention
    note_no_cust = "200 bag Ultratech cement dispatch karo."
    semantic_state = _compile(note_no_cust)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    assert validation.status == ValidationStatus.FAILED
    check_map = {c.check_type: c for c in validation.checks}
    cust_check = check_map["CUSTOMER_IDENTITY"]
    assert cust_check.status == ValidationStatus.FAILED
    assert cust_check.severity == ValidationSeverity.CRITICAL


def test_inventory_shortage_fails_validation() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()

    # Request 200 bags of ACC cement (only 120 available)
    note_acc = "Sharma Builders ko 200 bag ACC cement dispatch karo."
    semantic_state = _compile(note_acc)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    assert validation.status == ValidationStatus.FAILED
    check_map = {c.check_type: c for c in validation.checks}
    inv_check = check_map["INVENTORY_AVAILABILITY"]
    assert inv_check.status == ValidationStatus.FAILED
    assert "Inventory shortage" in inv_check.message


def test_fractional_bag_quantity_fails_validation() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()

    semantic_state = _compile(CANONICAL_VOICE_NOTE)
    # Manually inject fractional quantity: 200.5 bags
    semantic_state.items[0].quantity = SemanticQuantity(
        value=Decimal("200.5"),
        unit="bag",
        surface_text="200.5 bag",
        span=TextSpan(start=0, end=9),
        confidence=Confidence(score=0.99, source=ConfidenceSource.RULE),
    )
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )

    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    assert validation.status == ValidationStatus.FAILED
    check_map = {c.check_type: c for c in validation.checks}
    int_check = check_map["QUANTITY_INTEGER"]
    assert int_check.status == ValidationStatus.FAILED
    assert int_check.severity == ValidationSeverity.HIGH
