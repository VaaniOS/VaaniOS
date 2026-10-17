from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.domain.schemas.semantic import (
    Actionability,
    IntentType,
    RequestedActionType,
    SemanticEntityType,
    Urgency,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic.compiler import SemanticCompiler


def make_transcript(text: str) -> Transcript:
    return Transcript(
        transcript_id=uuid4(),
        provider="test",
        language="en-IN",
        detected_languages=["en-IN"],
        text=text,
        created_at=datetime.now(UTC),
    )


def test_compiler_extracts_dispatch_request() -> None:
    transcript = make_transcript(
        "Sharma Builders ko 200 bags UltraTech cement dispatch karo."
    )

    state = SemanticCompiler().compile(transcript)

    assert state.intent is IntentType.CREATE_DISPATCH_ORDER
    assert state.actionability is Actionability.COMPLETE

    assert any(
        entity.entity_type is SemanticEntityType.CUSTOMER
        and entity.surface_text == "Sharma Builders"
        for entity in state.entities
    )

    assert any(
        entity.entity_type is SemanticEntityType.PRODUCT
        and "UltraTech cement" in entity.surface_text
        for entity in state.entities
    )

    assert len(state.quantities) == 1
    assert state.quantities[0].value == 200
    assert state.quantities[0].unit == "bags"

    assert any(
        action.action_type is RequestedActionType.DISPATCH
        for action in state.requested_actions
    )


def test_compiler_extracts_invoice_and_approval() -> None:
    transcript = make_transcript(
        "Invoice bana ke approval ke liye bhej do."
    )

    state = SemanticCompiler().compile(transcript)

    assert state.intent is IntentType.CREATE_INVOICE

    action_types = {
        action.action_type
        for action in state.requested_actions
    }

    assert RequestedActionType.CREATE_INVOICE_DRAFT in action_types
    assert RequestedActionType.REQUEST_APPROVAL in action_types


def test_compiler_preserves_historical_price_reference() -> None:
    transcript = make_transcript(
        "Same rate lagana jo parso bataya tha."
    )

    state = SemanticCompiler().compile(transcript)

    assert any(
        reference.reference_type.value == "HISTORICAL_PRICE"
        for reference in state.references
    )

    assert any(
        expression.surface_text.casefold() == "parso"
        for expression in state.temporal_expressions
    )


def test_compiler_marks_missing_product_as_clarification() -> None:
    transcript = make_transcript(
        "Sharma Builders ko 200 bags dispatch karo."
    )

    state = SemanticCompiler().compile(transcript)

    assert state.actionability is Actionability.CLARIFICATION_REQUIRED

    assert any(
        ambiguity.field == "product"
        for ambiguity in state.ambiguities
    )


def test_compiler_marks_unknown_intent_as_blocked() -> None:
    transcript = make_transcript(
        "Hello, how are you?"
    )

    state = SemanticCompiler().compile(transcript)

    assert state.intent is IntentType.UNKNOWN
    assert state.actionability is Actionability.BLOCKED


def test_compiler_detects_urgent_request() -> None:
    transcript = make_transcript(
        "Urgently dispatch 200 bags to Sharma Builders."
    )

    state = SemanticCompiler().compile(transcript)

    assert state.urgency is Urgency.HIGH


def test_compiler_extracts_gst_constraint() -> None:
    transcript = make_transcript(
        "Send 200 bags UltraTech cement at 420 per bag plus GST."
    )

    state = SemanticCompiler().compile(transcript)

    assert any(
        constraint.field == "tax"
        and constraint.operator == "ADD"
        and constraint.value == "GST"
        for constraint in state.constraints
    )