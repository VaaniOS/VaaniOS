from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from vaaniflow.domain.schemas.semantic import SemanticState
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import InputEvaluation
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator

FIXED_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def make_transcript(text: str) -> Transcript:
    return Transcript(
        transcript_id=uuid4(),
        provider="test",
        language="en-IN",
        text=text,
        created_at=FIXED_TIME,
    )


def compile_text(text: str) -> SemanticState:
    return SemanticCompiler(clock=lambda: FIXED_TIME).compile(make_transcript(text))


def evaluate_text(text: str) -> tuple[SemanticState, InputEvaluation]:
    transcript = make_transcript(text)
    state = SemanticCompiler(clock=lambda: FIXED_TIME).compile(transcript)
    evaluation = InputEvaluator(clock=lambda: FIXED_TIME).evaluate(state, transcript=transcript)
    return state, evaluation


def summarize(state: SemanticState) -> dict[str, Any]:
    """Semantic content of a state without generated ids/timestamps."""
    reference_surface = {r.reference_id: r.surface_text for r in state.references}
    temporal_surface = {t.expression_id: t.surface_text for t in state.temporal_expressions}
    item_index = {item.item_id: index for index, item in enumerate(state.items)}

    return {
        "intent": state.intent.value,
        "customer": state.customer.surface_text if state.customer else None,
        "addressee": state.addressee.surface_text if state.addressee else None,
        "items": [
            (
                item.product.surface_text if item.product else None,
                item.quantity.value if item.quantity else None,
                item.quantity.unit if item.quantity else None,
            )
            for item in state.items
        ],
        "pricing": [
            (
                price.source.value,
                price.amount,
                price.currency,
                price.per_unit,
                item_index.get(price.item_id) if price.item_id else None,
                reference_surface.get(price.reference_id) if price.reference_id else None,
            )
            for price in state.pricing
        ],
        "tax": (state.tax.tax_type, state.tax.treatment.value, state.tax.surface_text)
        if state.tax
        else None,
        "references": [
            (
                r.reference_type.value,
                r.target_slot.value,
                r.surface_text,
                temporal_surface.get(r.temporal_expression_id)
                if r.temporal_expression_id
                else None,
            )
            for r in state.references
        ],
        "temporal": [
            (
                t.surface_text,
                t.kind.value,
                t.normalized_expression,
                t.direction.value,
                t.day_offset,
                t.target.value,
                t.resolution_status.value,
            )
            for t in state.temporal_expressions
        ],
        "corrections": [
            (c.field.value, c.previous_value.normalized, c.corrected_value.normalized)
            for c in state.corrections
        ],
        "ambiguities": [
            (a.ambiguity_type.value, a.slot.value, tuple(a.candidates)) for a in state.ambiguities
        ],
        "actions": [
            (
                a.action_type.value,
                a.recipient.value if a.recipient else None,
                a.channel,
            )
            for a in state.requested_actions
        ],
        "urgency": state.urgency.value,
    }


def reason_codes(evaluation: InputEvaluation) -> list[str]:
    return [reason.code.value for reason in evaluation.reasons]


@pytest.fixture
def compile_() -> Callable[[str], SemanticState]:
    return compile_text
