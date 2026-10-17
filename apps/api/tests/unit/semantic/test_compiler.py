"""Golden SemanticState tests for the deterministic compiler."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.semantic import SemanticState

from .conftest import compile_text, evaluate_text, reason_codes, summarize

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)


def _assert_spans_match_surface(text: str, state: SemanticState) -> None:
    spanned = [
        *(e for e in (state.customer, state.addressee) if e is not None),
        *(i.product for i in state.items if i.product is not None),
        *(i.quantity for i in state.items if i.quantity is not None),
        *state.pricing,
        *state.references,
        *state.temporal_expressions,
        *state.requested_actions,
        *([state.tax] if state.tax else []),
    ]
    for value in spanned:
        assert text[value.span.start : value.span.end] == value.surface_text


# --------------------------------------------------------------------------- #
# Canonical demo scenario
# --------------------------------------------------------------------------- #


def test_canonical_ramesh_voice_note_golden_state() -> None:
    state = compile_text(CANONICAL)

    assert summarize(state) == {
        "intent": "CREATE_DISPATCH_ORDER",
        "customer": "Sharma Builders",
        "addressee": "Suresh",
        "items": [("Ultratech cement", Decimal(200), "bag")],
        "pricing": [
            (
                "SPOKEN_WITH_HISTORICAL_REFERENCE",
                Decimal(420),
                "INR",
                "bag",
                0,
                "Rate wahi",
            )
        ],
        "tax": ("GST", "EXCLUSIVE", "plus GST"),
        "references": [("HISTORICAL_PRICE", "PRICE", "Rate wahi", "parso")],
        "temporal": [
            ("parso", "RELATIVE_DAY", "DAY_OFFSET:-2", "PAST", -2, "REFERENCE", "UNRESOLVED")
        ],
        "corrections": [],
        "ambiguities": [],
        "actions": [
            ("DISPATCH", None, None),
            ("CREATE_INVOICE_DRAFT", None, None),
            ("SEND_NOTIFICATION", "SPEAKER", "WHATSAPP"),
            ("REQUEST_APPROVAL", "SPEAKER", None),
        ],
        "urgency": "HIGH",
    }
    _assert_spans_match_surface(CANONICAL, state)


def test_canonical_scenario_is_partial_because_the_rate_is_a_reference() -> None:
    _, evaluation = evaluate_text(CANONICAL)

    assert evaluation.actionability is Actionability.PARTIAL
    assert reason_codes(evaluation) == [
        "CONTEXT_REFERENCE_UNRESOLVED",
        "RELATIVE_DATE_NEEDS_CLOCK",
    ]


def test_canonical_state_contains_no_business_facts() -> None:
    state = compile_text(CANONICAL)
    payload = json.loads(state.model_dump_json())

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    forbidden = {
        "customer_id",
        "product_id",
        "sku",
        "quote_id",
        "order_id",
        "invoice_id",
        "inventory",
        "available_quantity",
        "tax_amount",
        "total",
        "resolved_date",
        "resolved_datetime",
    }
    assert keys(payload) & forbidden == set()
    assert state.temporal_expressions[0].day is None  # no calendar date invented


def test_canonical_state_round_trips_through_json() -> None:
    state = compile_text(CANONICAL)

    assert SemanticState.model_validate_json(state.model_dump_json()) == state


# --------------------------------------------------------------------------- #
# Core extraction
# --------------------------------------------------------------------------- #


def test_simple_hinglish_dispatch() -> None:
    state = compile_text("Sharma Builders ko 200 bags UltraTech cement dispatch karo.")

    summary = summarize(state)
    assert summary["intent"] == "CREATE_DISPATCH_ORDER"
    assert summary["customer"] == "Sharma Builders"
    assert summary["items"] == [("UltraTech cement", Decimal(200), "bag")]
    assert summary["actions"] == [("DISPATCH", None, None)]
    assert state.intent_confidence.score == 0.9


def test_urgent_english_dispatch_does_not_mistake_adverb_for_customer() -> None:
    state = compile_text("Urgently dispatch 200 bags UltraTech cement to Sharma Builders.")

    summary = summarize(state)
    assert summary["customer"] == "Sharma Builders"
    assert summary["items"] == [("UltraTech cement", Decimal(200), "bag")]
    assert summary["urgency"] == "HIGH"


def test_product_does_not_swallow_destination_phrase() -> None:
    state = compile_text("Urgently dispatch 200 bags to Sharma Builders.")

    assert summarize(state)["customer"] == "Sharma Builders"
    assert summarize(state)["items"] == [(None, Decimal(200), "bag")]


def test_product_and_customer_are_split_when_adjacent() -> None:
    state = compile_text("100 bag ACC cement Kumar Constructions ko bhejo")

    summary = summarize(state)
    assert summary["items"] == [("ACC cement", Decimal(100), "bag")]
    assert summary["customer"] == "Kumar Constructions"
    assert summary["actions"] == [("DISPATCH", None, None)]


def test_multiple_line_items_keep_product_quantity_binding() -> None:
    state = compile_text(
        "Send 200 bags of UltraTech cement and 50 kg of steel rods to Kumar Constructions."
    )

    assert summarize(state)["items"] == [
        ("UltraTech cement", Decimal(200), "bag"),
        ("steel rods", Decimal(50), "kg"),
    ]
    assert summarize(state)["customer"] == "Kumar Constructions"


def test_quantity_before_and_after_product() -> None:
    state = compile_text("Kumar Constructions ko UltraTech cement 200 bags dispatch karo")

    assert summarize(state)["items"] == [("UltraTech cement", Decimal(200), "bag")]


def test_spoken_number_words_are_parsed() -> None:
    state = compile_text("Sharma Builders ko do sau bag ACC cement bhejo")

    assert summarize(state)["items"] == [("ACC cement", Decimal(200), "bag")]
    assert state.items[0].quantity is not None
    assert state.items[0].quantity.confidence.score == 0.85  # number words < digits


def test_structured_price_with_unit_and_currency() -> None:
    state = compile_text("Send 200 bags UltraTech cement to Sharma Builders at ₹420 per bag.")

    assert summarize(state)["pricing"] == [("SPOKEN", Decimal(420), "INR", "bag", 0, None)]


def test_price_without_currency_keeps_currency_unknown() -> None:
    state = compile_text("Send 200 bags UltraTech cement to Sharma Builders at 420 per bag.")

    assert summarize(state)["pricing"] == [("SPOKEN", Decimal(420), None, "bag", 0, None)]


def test_gst_exclusive_instruction() -> None:
    state = compile_text("Send 200 bags UltraTech cement at 420 per bag plus GST.")

    assert summarize(state)["tax"] == ("GST", "EXCLUSIVE", "plus GST")


def test_gst_inclusive_instruction() -> None:
    state = compile_text("Rate 420 per bag including GST, 100 bags ACC cement.")

    assert summarize(state)["tax"] == ("GST", "INCLUSIVE", "including GST")


def test_invoice_and_approval_without_dispatch() -> None:
    state = compile_text("Invoice bana ke approval ke liye bhej do.")

    summary = summarize(state)
    assert summary["intent"] == "CREATE_INVOICE"
    assert summary["actions"] == [
        ("CREATE_INVOICE_DRAFT", None, None),
        ("REQUEST_APPROVAL", "UNSPECIFIED", None),
    ]


def test_check_inventory_question() -> None:
    state = compile_text("What is the stock of UltraTech cement?")

    assert summarize(state)["intent"] == "CHECK_INVENTORY"
    assert summarize(state)["items"] == [("UltraTech cement", None, None)]


def test_check_price_question() -> None:
    state = compile_text("ACC cement ka rate kya hai?")

    assert summarize(state)["intent"] == "CHECK_PRICE"


def test_setting_a_rate_is_not_a_price_check() -> None:
    state = compile_text("Rate wahi lagana jo parso bataya tha.")

    assert summarize(state)["intent"] == "UNKNOWN"
    assert summarize(state)["references"][0][0] == "HISTORICAL_PRICE"


def test_cancel_order() -> None:
    state = compile_text("Cancel the order for Sharma Builders")

    assert summarize(state)["intent"] == "CANCEL_ORDER"
    assert summarize(state)["customer"] == "Sharma Builders"


def test_unknown_intent() -> None:
    state = compile_text("Hello, how are you?")

    summary = summarize(state)
    assert summary["intent"] == "UNKNOWN"
    assert summary["addressee"] is None
    assert summary["actions"] == []
    assert state.intent_confidence.score == 0.2


def test_facts_without_an_action() -> None:
    state = compile_text("Sharma Builders 200 bags UltraTech cement 420 rupees.")

    summary = summarize(state)
    assert summary["intent"] == "UNKNOWN"
    assert summary["items"] == [("UltraTech cement", Decimal(200), "bag")]
    assert summary["pricing"] == [("SPOKEN", Decimal(420), "INR", None, 0, None)]


@pytest.mark.parametrize("text", ["   ", "...", "—", "?!"])
def test_blank_or_punctuation_only_input_compiles_to_empty_unknown_state(text: str) -> None:
    state = compile_text(text)

    assert summarize(state) == {
        "intent": "UNKNOWN",
        "customer": None,
        "addressee": None,
        "items": [],
        "pricing": [],
        "tax": None,
        "references": [],
        "temporal": [],
        "corrections": [],
        "ambiguities": [],
        "actions": [],
        "urgency": "NORMAL",
    }


NOISY_ASR = (
    "arre suresh sharma builders ko turant do sau bag ultratech cement dispatch karo "
    "rate wahi jo parso bataya tha chaar sau bees rupaye per bag plus gst"
)


def test_lowercase_unpunctuated_asr_transcript() -> None:
    state = compile_text(NOISY_ASR)

    summary = summarize(state)
    assert summary["intent"] == "CREATE_DISPATCH_ORDER"
    assert summary["items"] == [("ultratech cement", Decimal(200), "bag")]
    assert summary["pricing"] == [
        ("SPOKEN_WITH_HISTORICAL_REFERENCE", Decimal(420), "INR", "bag", 0, "rate wahi")
    ]
    assert summary["temporal"] == [
        ("parso", "RELATIVE_DAY", "DAY_OFFSET:-2", "PAST", -2, "REFERENCE", "UNRESOLVED")
    ]
    assert summary["tax"] == ("GST", "EXCLUSIVE", "plus gst")
    # Without the comma, "suresh" cannot be separated from the customer name.
    assert summary["addressee"] is None
    assert summary["customer"] == "suresh sharma builders"
    assert state.customer is not None
    assert state.customer.confidence.score == 0.4


def test_unpunctuated_addressee_overlap_requires_clarification() -> None:
    _, evaluation = evaluate_text(NOISY_ASR)

    assert evaluation.actionability is Actionability.CLARIFICATION_REQUIRED
    assert "LOW_CONFIDENCE_SLOT" in reason_codes(evaluation)


def test_devanagari_transcript_is_not_misread() -> None:
    """Devanagari is unsupported: it must yield nothing rather than wrong facts."""
    state = compile_text("शर्मा बिल्डर्स को 200 बैग अल्ट्राटेक सीमेंट भेजो")

    assert state.intent.value == "UNKNOWN"
    assert state.customer is None
    assert state.items == []


def test_compiler_records_provenance() -> None:
    state = compile_text(CANONICAL)

    assert state.schema_version == "2.0"
    assert state.compiler.compiler_name == "vaaniflow.deterministic-compiler"
    assert state.compiler.compiler_version == "2.0.0"
