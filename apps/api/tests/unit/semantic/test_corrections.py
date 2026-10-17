"""Corrections preserve history and the current state holds the corrected value."""

from __future__ import annotations

from decimal import Decimal

import pytest

from .conftest import compile_text, summarize


def test_quantity_correction_with_inherited_unit() -> None:
    state = compile_text("Send 200 bags UltraTech cement to Sharma Builders, actually 220.")

    assert summarize(state)["items"] == [("UltraTech cement", Decimal(220), "bag")]
    assert summarize(state)["corrections"] == [("QUANTITY", "200 bag", "220 bag")]

    correction = state.corrections[0]
    assert correction.previous_value.amount == Decimal(200)
    assert correction.previous_value.surface_text == "200 bags"
    assert correction.corrected_value.amount == Decimal(220)
    assert correction.corrected_value.unit == "bag"
    assert correction.marker == "actually"
    assert correction.target_id == state.items[0].item_id
    assert correction.source_text == "200 bags UltraTech cement to Sharma Builders, actually 220"


def test_unitless_number_corrected_by_number_with_unit() -> None:
    """System-Design 05 §5.10: "Send 200—actually 220 bags ..."."""
    state = compile_text("Send 200—actually 220 bags UltraTech cement to Sharma Builders.")

    assert summarize(state)["items"] == [("UltraTech cement", Decimal(220), "bag")]
    assert summarize(state)["corrections"] == [("QUANTITY", "200", "220 bag")]


@pytest.mark.parametrize(
    "text",
    [
        "Send 200 bags, actually 220 bags of ACC cement to Kumar Constructions.",
        "Send 200 bags... sorry, 220 bags of ACC cement to Kumar Constructions.",
        "Send 200 bags - no, 220 bags of ACC cement to Kumar Constructions.",
        "Send 200 bags, I mean 220 bags of ACC cement to Kumar Constructions.",
        "Send 200 bags, make that 220 bags of ACC cement to Kumar Constructions.",
        "Kumar Constructions ko 200 bag, nahi nahi, 220 bag ACC cement bhejo.",
    ],
)
def test_spoken_correction_marker_variants(text: str) -> None:
    state = compile_text(text)

    assert summarize(state)["items"] == [("ACC cement", Decimal(220), "bag")]
    assert [c.field.value for c in state.corrections] == ["QUANTITY"]


def test_multiple_corrections_chain_and_keep_full_history() -> None:
    state = compile_text(
        "Send 200 bags, actually 220, no, 250 bags UltraTech cement to Peenya Infra Works."
    )

    assert summarize(state)["items"] == [("UltraTech cement", Decimal(250), "bag")]
    assert summarize(state)["corrections"] == [
        ("QUANTITY", "200 bag", "220 bag"),
        ("QUANTITY", "220 bag", "250 bag"),
    ]


def test_price_correction() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags cement at 420, sorry 410 per bag dispatch karo."
    )

    assert summarize(state)["pricing"] == [("SPOKEN", Decimal(410), None, "bag", 0, None)]
    assert summarize(state)["corrections"] == [("PRICE", "420", "410 bag")]
    assert state.corrections[0].target_id == state.pricing[0].price_id


def test_price_correction_inherits_currency_and_unit() -> None:
    state = compile_text(
        "ACC cement 100 bags Kumar Constructions ko bhejo, rate ₹400 per bag, sorry 390."
    )

    assert summarize(state)["pricing"] == [("SPOKEN", Decimal(390), "INR", "bag", 0, None)]
    assert summarize(state)["corrections"] == [("PRICE", "400 bag", "390 bag")]


def test_customer_correction() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo, nahi nahi, Sharma Buildtech ko."
    )

    assert summarize(state)["customer"] == "Sharma Buildtech"
    assert summarize(state)["corrections"] == [("CUSTOMER", "sharma builders", "sharma buildtech")]
    assert state.corrections[0].previous_value.surface_text == "Sharma Builders"
    assert state.customer is not None
    assert state.corrections[0].target_id == state.customer.entity_id
    assert state.ambiguities == []


def test_product_correction_rebinds_the_quantity() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags UltraTech cement, sorry, ACC cement dispatch karo."
    )

    assert summarize(state)["items"] == [("ACC cement", Decimal(200), "bag")]
    assert summarize(state)["corrections"] == [("PRODUCT", "ultratech cement", "acc cement")]
    assert state.corrections[0].target_id == state.items[0].item_id


def test_unit_correction() -> None:
    state = compile_text("Send 50 bags, sorry, 50 kg steel rods to Kumar Constructions.")

    assert summarize(state)["items"] == [("steel rods", Decimal(50), "kg")]
    assert summarize(state)["corrections"] == [("UNIT", "50 bag", "50 kg")]


def test_temporal_correction_inherits_direction() -> None:
    state = compile_text("Kal dispatch karo, nahi, parso, Sharma Builders ko 100 bags ACC cement.")

    assert summarize(state)["corrections"] == [("DATE", "DAY_OFFSET:+1", "DAY_OFFSET:+2")]
    assert state.temporal_expressions[0].direction_evidence == (
        "inherited from corrected expression 'Kal'"
    )
    assert summarize(state)["temporal"] == [
        ("parso", "RELATIVE_DAY", "DAY_OFFSET:+2", "FUTURE", 2, "EXECUTION", "UNRESOLVED")
    ]
    assert state.ambiguities == []


@pytest.mark.parametrize(
    "text",
    [
        "Send 200 bags now to Kumar Constructions and 50 kg steel rods.",
        "You know, send 200 bags ACC cement to Noida Traders and 50 kg steel rods.",
        "Notify Kumar Constructions: 200 bags ACC cement and 50 kg steel rods.",
        "Note the notebook order: 200 bags ACC cement and 50 kg steel rods for Kumar Constructions.",
        "Invoice no 23 for Kumar Constructions: 200 bags ACC cement and 50 kg steel rods.",
    ],
)
def test_words_containing_no_are_not_correction_markers(text: str) -> None:
    state = compile_text(text)

    assert state.corrections == []
    assert [(i.quantity.value, i.quantity.unit) for i in state.items if i.quantity] == [
        (Decimal(200), "bag"),
        (Decimal(50), "kg"),
    ]


def test_additive_actually_is_not_a_correction() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags ACC cement bhejo, actually Kumar Constructions ko bhi."
    )

    assert state.corrections == []


def test_marker_without_replacement_is_ignored() -> None:
    state = compile_text("Actually, send 200 bags ACC cement to Kumar Constructions.")

    assert state.corrections == []
    assert summarize(state)["items"] == [("ACC cement", Decimal(200), "bag")]


def test_price_never_replaces_a_quantity() -> None:
    state = compile_text("Send 200 bags ACC cement to Kumar Constructions, sorry, ₹410 per bag.")

    assert state.corrections == []
    assert summarize(state)["items"] == [("ACC cement", Decimal(200), "bag")]
    assert summarize(state)["pricing"] == [("SPOKEN", Decimal(410), "INR", "bag", 0, None)]
