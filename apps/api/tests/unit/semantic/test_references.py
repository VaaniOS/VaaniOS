"""References are recorded with their target slot and never resolved."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vaaniflow.domain.schemas.semantic import PriceSource, ReferenceType, SemanticSlot
from vaaniflow.semantic.references import extract_references

from .conftest import compile_text, summarize


@pytest.mark.parametrize(
    ("text", "reference_type", "slot", "surface"),
    [
        ("Use the same rate we discussed.", ReferenceType.HISTORICAL_PRICE, SemanticSlot.PRICE, "same rate"),
        ("Usual rate pe dena.", ReferenceType.HISTORICAL_PRICE, SemanticSlot.PRICE, "Usual rate"),
        ("Rate wahi lagana.", ReferenceType.HISTORICAL_PRICE, SemanticSlot.PRICE, "Rate wahi"),
        ("Usi rate pe dena.", ReferenceType.HISTORICAL_PRICE, SemanticSlot.PRICE, "Usi rate"),
        ("Use the previous quote.", ReferenceType.HISTORICAL_QUOTE, SemanticSlot.QUOTE, "previous quote"),
        ("Send it to the same customer.", ReferenceType.CUSTOMER, SemanticSlot.CUSTOMER, "same customer"),
        ("Send 100 bags of that product.", ReferenceType.PRODUCT, SemanticSlot.PRODUCT, "that product"),
        ("Cancel that order.", ReferenceType.ORDER, SemanticSlot.ORDER, "that order"),
        ("Send the same quantity.", ReferenceType.PREVIOUS_VALUE, SemanticSlot.QUANTITY, "same quantity"),
    ],
)  # fmt: skip
def test_reference_phrases(
    text: str,
    reference_type: ReferenceType,
    slot: SemanticSlot,
    surface: str,
) -> None:
    references = [
        r for r in extract_references(text) if r.reference_type is not ReferenceType.PRONOUN
    ]

    assert [(r.reference_type, r.target_slot, r.surface_text) for r in references] == [
        (reference_type, slot, surface)
    ]


@pytest.mark.parametrize(
    ("text", "slot"),
    [
        ("Send it to Kumar Constructions.", SemanticSlot.UNKNOWN),
        ("Dispatch them tomorrow.", SemanticSlot.UNKNOWN),
        ("Cancel it.", SemanticSlot.ORDER),
        ("Usko bhejo Sharma Builders ko.", SemanticSlot.UNKNOWN),
    ],
)
def test_pronoun_objects_are_context_dependent_references(text: str, slot: SemanticSlot) -> None:
    references = extract_references(text)

    assert [(r.reference_type, r.target_slot) for r in references] == [
        (ReferenceType.PRONOUN, slot)
    ]


def test_pronouns_outside_an_action_are_not_references() -> None:
    assert extract_references("It is raining and that is fine.") == []


def test_historical_price_reference_becomes_a_price_slot() -> None:
    state = compile_text("Sharma Builders ko 100 bags ACC cement bhejo, same rate.")

    assert summarize(state)["pricing"] == [
        ("HISTORICAL_REFERENCE", None, None, None, 0, "same rate")
    ]
    assert state.pricing[0].reference_id == state.references[0].reference_id


def test_spoken_price_is_linked_to_the_historical_reference_it_restates() -> None:
    state = compile_text(
        "Same rate as parso, ₹420 per bag, 100 bags ACC cement Sharma Builders ko."
    )

    assert state.pricing[0].source is PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE
    assert state.pricing[0].amount == Decimal(420)
    assert state.pricing[0].reference_id == state.references[0].reference_id


def test_historical_quote_reference_supplies_the_price_slot() -> None:
    state = compile_text(
        "Use the previous quote for Sharma Builders 100 bags ACC cement and dispatch."
    )

    assert summarize(state)["pricing"] == [
        ("HISTORICAL_REFERENCE", None, None, None, 0, "previous quote")
    ]


def test_reference_is_anchored_to_its_temporal_expression() -> None:
    state = compile_text("Same rate as parso.")

    reference = state.references[0]
    expression = state.temporal_expressions[0]
    assert reference.temporal_expression_id == expression.expression_id
    assert expression.direction.value == "PAST"
    assert expression.direction_evidence == "qualifies historical reference 'Same rate'"


def test_product_reference_attaches_to_the_item_it_completes() -> None:
    state = compile_text("Send 100 bags of the same product to Kumar Constructions.")

    assert summarize(state)["items"] == [(None, Decimal(100), "bag")]
    assert state.references[0].item_id == state.items[0].item_id


def test_compiler_does_not_resolve_references_to_business_values() -> None:
    state = compile_text("Sharma Builders ko 100 bags ACC cement bhejo, same rate.")

    price = state.pricing[0]
    assert price.amount is None
    assert price.currency is None
    assert state.customer is not None
    assert state.customer.normalized_text == "sharma builders"
