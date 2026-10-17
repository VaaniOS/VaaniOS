"""SemanticState 2.0 contract: shape, invariants and absence of business facts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from vaaniflow.domain.schemas.common import ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    IntentType,
    PriceSource,
    ReferenceType,
    SemanticEntityType,
    SemanticSlot,
    SemanticState,
    TemporalKind,
    TemporalResolutionStatus,
)

CONF = {"score": 0.9, "source": ConfidenceSource.RULE}
SPAN = {"start": 0, "end": 5}


def _entity(entity_type: SemanticEntityType) -> dict[str, Any]:
    return {
        "entity_id": uuid4(),
        "entity_type": entity_type,
        "surface_text": "Sharma",
        "normalized_text": "sharma",
        "span": SPAN,
        "confidence": CONF,
    }


def _state(**overrides: Any) -> SemanticState:
    base: dict[str, Any] = {
        "semantic_state_id": uuid4(),
        "source_transcript_id": uuid4(),
        "compiler": {"compiler_name": "test", "compiler_version": "1"},
        "intent": IntentType.CREATE_DISPATCH_ORDER,
        "intent_confidence": CONF,
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return SemanticState(**base)


def test_minimal_state_is_valid_and_versioned() -> None:
    state = _state()

    assert state.schema_version == "2.0"
    assert state.version == 1
    assert state.run_id is None
    assert state.items == []


def test_schema_version_cannot_be_changed() -> None:
    with pytest.raises(ValidationError):
        _state(schema_version="1.0")


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _state(customer_id="CUST-0042")


def test_contract_has_no_business_identifier_fields() -> None:
    def field_names(model: type[BaseModel]) -> set[str]:
        names: set[str] = set()
        for name, info in model.model_fields.items():
            names.add(name)
            annotation = info.annotation
            for candidate in getattr(annotation, "__args__", (annotation,)):
                inner = getattr(candidate, "__args__", (candidate,))
                for leaf in inner:
                    if hasattr(leaf, "model_fields") and leaf is not model:
                        names |= field_names(leaf)
        return names

    names = field_names(SemanticState)
    assert (
        names
        & {
            "customer_id",
            "product_id",
            "sku",
            "quote_id",
            "order_id",
            "invoice_id",
            "inventory_id",
            "resolved_datetime",
            "resolved_date",
            "tax_amount",
        }
        == set()
    )


def test_customer_slot_must_hold_a_customer_entity() -> None:
    with pytest.raises(ValidationError):
        _state(customer=_entity(SemanticEntityType.PRODUCT))


def test_item_needs_product_or_quantity() -> None:
    with pytest.raises(ValidationError):
        _state(items=[{"item_id": uuid4()}])


def test_item_product_must_be_a_product_entity() -> None:
    with pytest.raises(ValidationError):
        _state(items=[{"item_id": uuid4(), "product": _entity(SemanticEntityType.CUSTOMER)}])


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _state(
            items=[
                {
                    "item_id": uuid4(),
                    "quantity": {
                        "value": Decimal(0),
                        "unit": "bag",
                        "surface_text": "0 bags",
                        "span": SPAN,
                        "confidence": CONF,
                    },
                }
            ]
        )


def _price(**overrides: Any) -> dict[str, Any]:
    price: dict[str, Any] = {
        "price_id": uuid4(),
        "source": PriceSource.SPOKEN,
        "amount": Decimal(420),
        "currency": "INR",
        "per_unit": "bag",
        "surface_text": "₹420 per bag",
        "span": SPAN,
        "confidence": CONF,
    }
    price.update(overrides)
    return price


def _reference() -> dict[str, Any]:
    return {
        "reference_id": uuid4(),
        "reference_type": ReferenceType.HISTORICAL_PRICE,
        "target_slot": SemanticSlot.PRICE,
        "surface_text": "same rate",
        "normalized_text": "same rate",
        "span": SPAN,
        "confidence": CONF,
    }


def test_price_source_must_match_amount_and_reference() -> None:
    reference = _reference()

    _state(
        references=[reference],
        pricing=[
            _price(
                source=PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE,
                reference_id=reference["reference_id"],
            )
        ],
    )

    with pytest.raises(ValidationError):
        _state(pricing=[_price(source=PriceSource.HISTORICAL_REFERENCE)])
    with pytest.raises(ValidationError):
        _state(pricing=[_price(amount=None)])


def test_price_must_point_to_an_existing_item_and_reference() -> None:
    with pytest.raises(ValidationError):
        _state(pricing=[_price(item_id=uuid4())])
    with pytest.raises(ValidationError):
        _state(
            pricing=[
                _price(source=PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE, reference_id=uuid4())
            ]
        )


def test_reference_must_point_to_an_existing_temporal_expression() -> None:
    with pytest.raises(ValidationError):
        _state(references=[{**_reference(), "temporal_expression_id": uuid4()}])


def _temporal(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "expression_id": uuid4(),
        "surface_text": "parso",
        "span": SPAN,
        "kind": TemporalKind.RELATIVE_DAY,
        "normalized_expression": "DAY_OFFSET:±2",
        "direction": "UNKNOWN",
        "resolution_status": TemporalResolutionStatus.AMBIGUOUS,
        "confidence": CONF,
    }
    value.update(overrides)
    return value


def test_ambiguous_temporal_expressions_cannot_carry_an_offset() -> None:
    _state(temporal_expressions=[_temporal()])

    with pytest.raises(ValidationError):
        _state(temporal_expressions=[_temporal(day_offset=-2)])


def test_unresolved_relative_day_requires_an_offset() -> None:
    with pytest.raises(ValidationError):
        _state(temporal_expressions=[_temporal(resolution_status="UNRESOLVED")])


def test_absolute_date_requires_a_year() -> None:
    with pytest.raises(ValidationError):
        _state(
            temporal_expressions=[
                _temporal(
                    kind=TemporalKind.EXPLICIT_DATE,
                    normalized_expression="DATE:--10-25",
                    day=25,
                    month=10,
                    resolution_status=TemporalResolutionStatus.ABSOLUTE,
                )
            ]
        )


def test_spans_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _state(customer={**_entity(SemanticEntityType.CUSTOMER), "span": {"start": 5, "end": 5}})


def test_confidence_score_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        _state(intent_confidence={"score": 1.5, "source": ConfidenceSource.MODEL})
