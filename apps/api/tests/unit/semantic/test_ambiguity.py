"""Semantic ambiguity is detected; business-context ambiguity is left downstream."""

from __future__ import annotations

from vaaniflow.domain.schemas.semantic import AmbiguityType, SemanticSlot

from .conftest import compile_text, summarize


def test_conflicting_quantities_for_the_same_product() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo. 250 bags UltraTech cement."
    )

    assert summarize(state)["items"] == [("UltraTech cement", None, None)]
    assert summarize(state)["ambiguities"] == [
        ("VALUE_AMBIGUITY", "QUANTITY", ("200 bags", "250 bags"))
    ]
    assert state.ambiguities[0].related_ids == [state.items[0].item_id]


def test_repeating_the_same_quantity_is_not_a_conflict() -> None:
    state = compile_text(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo. Haan, 200 bags UltraTech cement."
    )

    assert state.ambiguities == []
    assert len(state.items) == 1


def test_two_different_customers_without_a_correction() -> None:
    state = compile_text(
        "Sharma Builders ko 100 bags ACC cement dispatch karo, Kumar Constructions ko bhejo."
    )

    assert state.customer is None
    assert summarize(state)["ambiguities"] == [
        ("ENTITY_AMBIGUITY", "CUSTOMER", ("Sharma Builders", "Kumar Constructions"))
    ]


def test_one_price_for_several_items_is_a_scope_ambiguity() -> None:
    state = compile_text(
        "Send 200 bags of UltraTech cement and 50 kg of steel rods to Kumar Constructions "
        "at ₹420 per piece."
    )

    assert [a.ambiguity_type for a in state.ambiguities] == [AmbiguityType.SCOPE_AMBIGUITY]
    assert state.pricing[0].item_id is None


def test_price_unit_selects_the_item_it_applies_to() -> None:
    state = compile_text(
        "Send 200 bags of UltraTech cement and 50 kg of steel rods to Kumar Constructions "
        "at ₹60 per kg."
    )

    assert state.ambiguities == []
    assert state.pricing[0].item_id == state.items[1].item_id


def test_conflicting_spoken_prices_for_one_item() -> None:
    state = compile_text(
        "Kumar Constructions ko 100 bags ACC cement bhejo, ₹400 per bag. ₹380 per bag."
    )

    assert [(a.ambiguity_type, a.slot) for a in state.ambiguities] == [
        (AmbiguityType.VALUE_AMBIGUITY, SemanticSlot.PRICE)
    ]


def test_cancel_and_dispatch_together_is_an_action_ambiguity() -> None:
    state = compile_text(
        "Cancel the order and dispatch 100 bags ACC cement to Kumar Constructions."
    )

    assert summarize(state)["ambiguities"] == [
        ("ACTION_AMBIGUITY", "ACTION", ("CANCEL_ORDER", "DISPATCH"))
    ]
    assert state.intent_confidence.score == 0.45


def test_untensed_bidirectional_day_word_is_a_temporal_ambiguity() -> None:
    state = compile_text("Sharma Builders, 100 bags ACC cement, parso.")

    assert summarize(state)["ambiguities"] == [
        ("TEMPORAL_AMBIGUITY", "DATE", ("DAY_OFFSET:-2", "DAY_OFFSET:+2"))
    ]


def test_a_single_customer_name_is_never_a_semantic_ambiguity() -> None:
    """Whether 'Sharma Builders' matches several records is decided downstream."""
    state = compile_text("Sharma Builders ko 200 bags UltraTech cement dispatch karo.")

    assert state.ambiguities == []
    assert {a.value for a in AmbiguityType} == {
        "ENTITY_AMBIGUITY",
        "VALUE_AMBIGUITY",
        "TEMPORAL_AMBIGUITY",
        "ACTION_AMBIGUITY",
        "REFERENCE_AMBIGUITY",
        "SCOPE_AMBIGUITY",
    }
