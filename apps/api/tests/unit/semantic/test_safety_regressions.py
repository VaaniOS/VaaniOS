"""
Safety regressions from the pre-push audit: UNDERSTAND must never invert or
silently resolve what the user said.

    "don't dispatch"      ≠ dispatch
    "UltraTech ya ACC"    ≠ one product
    "200 ya 300"          ≠ 300
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.semantic import SemanticState

from .conftest import evaluate_text, reason_codes, summarize

Q = Actionability.CLARIFICATION_REQUIRED
B = Actionability.BLOCKED


def _negated(state: SemanticState) -> list[tuple[str, str]]:
    return [(a.action_type.value, a.surface_text) for a in state.negated_actions]


# --------------------------------------------------------------------------- #
# P0 — negated actions
# --------------------------------------------------------------------------- #


def test_dont_dispatch_with_full_request_is_not_a_dispatch() -> None:
    state, evaluation = evaluate_text(
        "Don't dispatch 200 bags of UltraTech cement to Sharma Builders"
    )

    summary = summarize(state)
    assert summary["intent"] == "UNKNOWN"
    assert summary["actions"] == []
    assert _negated(state) == [("DISPATCH", "Don't dispatch")]
    assert summary["customer"] == "Sharma Builders"
    assert summary["items"] == [("UltraTech cement", Decimal(200), "bag")]
    assert summary["ambiguities"] == []
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["NEGATED_ACTION"]
    assert evaluation.reasons[0].related_ids == [state.negated_actions[0].action_id]


def test_do_not_dispatch() -> None:
    state, evaluation = evaluate_text("Do not dispatch 200 bags of UltraTech cement")

    assert summarize(state)["actions"] == []
    assert _negated(state) == [("DISPATCH", "Do not dispatch")]
    assert summarize(state)["items"] == [("UltraTech cement", Decimal(200), "bag")]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["NEGATED_ACTION"]


def test_never_dispatch() -> None:
    state, evaluation = evaluate_text(
        "Never dispatch 200 bags of UltraTech cement to Sharma Builders."
    )

    assert _negated(state) == [("DISPATCH", "Never dispatch")]
    assert summarize(state)["actions"] == []
    assert evaluation.actionability is Q


def test_typographic_apostrophe_dont() -> None:
    state, evaluation = evaluate_text("Don’t dispatch 200 bags of UltraTech cement.")

    assert _negated(state) == [("DISPATCH", "Don’t dispatch")]
    assert evaluation.actionability is Q


@pytest.mark.parametrize(
    ("text", "surface", "actionability", "codes"),
    [
        ("Dispatch mat karo", "Dispatch mat", B, ["NO_ACTIONABLE_INTENT", "NEGATED_ACTION"]),
        ("Dispatch nahi karna", "Dispatch nahi", B, ["NO_ACTIONABLE_INTENT", "NEGATED_ACTION"]),
        ("Abhi dispatch nahi karna", "dispatch nahi", B, ["NO_ACTIONABLE_INTENT", "NEGATED_ACTION"]),
        (
            "Sharma Builders ko 200 bags UltraTech cement dispatch mat karo.",
            "dispatch mat",
            Q,
            ["NEGATED_ACTION"],
        ),
        (
            "Sharma Builders ko 200 bags UltraTech cement dispatch mat karna.",
            "dispatch mat",
            Q,
            ["NEGATED_ACTION"],
        ),
        (
            "Sharma Builders ko 200 bags UltraTech cement abhi dispatch nahi karna.",
            "dispatch nahi",
            Q,
            ["NEGATED_ACTION"],
        ),
        ("Sharma Builders ko 200 bags ACC cement mat bhejo.", "mat bhejo", Q, ["NEGATED_ACTION"]),
    ],
)  # fmt: skip
def test_hinglish_negated_dispatch(
    text: str,
    surface: str,
    actionability: Actionability,
    codes: list[str],
) -> None:
    state, evaluation = evaluate_text(text)

    assert summarize(state)["intent"] == "UNKNOWN"
    assert summarize(state)["actions"] == []
    assert _negated(state) == [("DISPATCH", surface)]
    assert evaluation.actionability is actionability
    assert reason_codes(evaluation) == codes


def test_negating_one_action_keeps_the_others_but_blocks_completion() -> None:
    state, evaluation = evaluate_text(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo, invoice mat banao."
    )

    assert summarize(state)["actions"] == [("DISPATCH", None, None)]
    assert _negated(state) == [("CREATE_INVOICE_DRAFT", "invoice mat")]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["NEGATED_ACTION"]


def test_action_both_requested_and_negated_is_an_action_ambiguity() -> None:
    state, evaluation = evaluate_text(
        "Sharma Builders ko 200 bags ACC cement dispatch karo. Dispatch mat karo."
    )

    assert summarize(state)["actions"] == [("DISPATCH", None, None)]
    assert _negated(state) == [("DISPATCH", "Dispatch mat")]
    assert summarize(state)["ambiguities"] == [("ACTION_AMBIGUITY", "ACTION", ("DISPATCH",))]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["NEGATED_ACTION", "SEMANTIC_AMBIGUITY"]


@pytest.mark.parametrize(
    "text",
    [
        "Dispatch day after tomorrow, not tomorrow, 100 bags ACC cement to Kumar Constructions.",
        "Kumar Constructions ko 200 bag, nahi nahi, 220 bag ACC cement bhejo.",
        "Kal dispatch karo, nahi, parso, Sharma Builders ko 100 bags ACC cement.",
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo, nahi nahi, Sharma Buildtech ko.",
    ],
)
def test_corrections_with_not_or_nahi_are_not_action_negation(text: str) -> None:
    state, _ = evaluate_text(text)

    assert state.negated_actions == []
    assert [a.action_type.value for a in state.requested_actions] == ["DISPATCH"]


# --------------------------------------------------------------------------- #
# P0 — product / customer alternatives
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo.",
        "Send 200 bags of UltraTech or ACC cement to Sharma Builders.",
        "Sharma Builders ko 200 bags UltraTech cement ya ACC cement dispatch karo.",
    ],
)
def test_product_alternatives_are_not_resolved_to_one_product(text: str) -> None:
    state, evaluation = evaluate_text(text)

    summary = summarize(state)
    assert summary["items"] == [(None, Decimal(200), "bag")]
    assert summary["ambiguities"] == [
        ("ENTITY_AMBIGUITY", "PRODUCT", ("UltraTech cement", "ACC cement"))
    ]
    assert state.ambiguities[0].related_ids == [state.items[0].item_id]
    assert summary["actions"] == [("DISPATCH", None, None)]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["SEMANTIC_AMBIGUITY"]


def test_product_alternatives_without_quantity() -> None:
    state, evaluation = evaluate_text("Dispatch UltraTech or ACC cement to Kumar Constructions.")

    summary = summarize(state)
    assert summary["items"] == []
    assert summary["ambiguities"] == [
        ("ENTITY_AMBIGUITY", "PRODUCT", ("UltraTech cement", "ACC cement"))
    ]
    assert evaluation.actionability is Q


def test_positional_product_alternatives() -> None:
    state, evaluation = evaluate_text("Kumar Constructions ko 200 bags Birla ya JK dispatch karo.")

    assert summarize(state)["ambiguities"] == [("ENTITY_AMBIGUITY", "PRODUCT", ("Birla", "JK"))]
    assert summarize(state)["items"] == [(None, Decimal(200), "bag")]
    assert evaluation.actionability is Q


def test_customer_alternatives_are_not_resolved_to_one_customer() -> None:
    state, evaluation = evaluate_text(
        "Sharma Builders ya Kumar Constructions ko 200 bags UltraTech cement dispatch karo."
    )

    assert state.customer is None
    assert summarize(state)["ambiguities"] == [
        ("ENTITY_AMBIGUITY", "CUSTOMER", ("Sharma Builders", "Kumar Constructions"))
    ]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["SEMANTIC_AMBIGUITY"]


# --------------------------------------------------------------------------- #
# P0 — quantity / price alternatives
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", ["Dispatch 200 ya 300 bags", "Dispatch 200 or 300 bags"])
def test_quantity_alternatives_without_product(text: str) -> None:
    state, evaluation = evaluate_text(text)

    summary = summarize(state)
    assert summary["items"] == []
    assert summary["ambiguities"] == [("VALUE_AMBIGUITY", "QUANTITY", ("200 bag", "300 bag"))]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["MISSING_CUSTOMER", "SEMANTIC_AMBIGUITY"]


def test_quantity_alternatives_bound_to_a_product() -> None:
    state, evaluation = evaluate_text(
        "Sharma Builders ko 200 ya 300 bags UltraTech cement dispatch karo."
    )

    summary = summarize(state)
    assert summary["items"] == [("UltraTech cement", None, None)]
    assert summary["ambiguities"] == [("VALUE_AMBIGUITY", "QUANTITY", ("200 bag", "300 bag"))]
    assert state.ambiguities[0].related_ids == [state.items[0].item_id]
    assert evaluation.actionability is Q
    assert reason_codes(evaluation) == ["SEMANTIC_AMBIGUITY"]


def test_small_number_word_alternatives_are_both_kept() -> None:
    state, _ = evaluate_text("Kumar Constructions ko do ya teen bag ACC cement bhejo.")

    assert summarize(state)["ambiguities"] == [("VALUE_AMBIGUITY", "QUANTITY", ("2 bag", "3 bag"))]


def test_price_alternatives_are_not_resolved_to_one_price() -> None:
    state, evaluation = evaluate_text(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo, rate 400 ya 420 rupaye per bag."
    )

    summary = summarize(state)
    assert summary["pricing"] == []
    assert summary["ambiguities"] == [
        ("VALUE_AMBIGUITY", "PRICE", ("400 INR per bag", "420 INR per bag"))
    ]
    assert evaluation.actionability is Q


# --------------------------------------------------------------------------- #
# P1 — fidelity and previously untested behaviour
# --------------------------------------------------------------------------- #


def test_asr_magnitude_is_preserved_exactly() -> None:
    """2000 is extracted faithfully; judging the magnitude is ACT validation."""
    state, evaluation = evaluate_text("Sharma Builders ko 2000 bag Ultratech cement dispatch karo.")

    assert summarize(state)["items"] == [("Ultratech cement", Decimal(2000), "bag")]
    assert state.items[0].quantity is not None
    assert state.items[0].quantity.surface_text == "2000 bag"
    assert evaluation.actionability is Actionability.COMPLETE


def test_fallback_product_without_category_noun() -> None:
    state, evaluation = evaluate_text("Kumar Constructions ko 200 bags Birla Gold dispatch karo.")

    assert summarize(state)["items"] == [("Birla Gold", Decimal(200), "bag")]
    assert state.items[0].product is not None
    assert state.items[0].product.confidence.score == 0.55
    assert evaluation.actionability is Actionability.COMPLETE


def test_fallback_product_is_not_taken_from_a_customer_name() -> None:
    state, _ = evaluate_text("200 bags Sharma Builders ko bhejo.")

    assert summarize(state)["items"] == [(None, Decimal(200), "bag")]
    assert summarize(state)["customer"] == "Sharma Builders"


def test_hedged_quantity_is_currently_kept_as_stated_value() -> None:
    """Known limitation: "around"/"lagbhag" is not represented (documented)."""
    state, _ = evaluate_text("Sharma Builders ko lagbhag 200 bags UltraTech cement dispatch karo.")

    assert summarize(state)["items"] == [("UltraTech cement", Decimal(200), "bag")]
