"""
UNDERSTAND → ACT handoff contract.

These tests play the consumer role: they only use the public
UnderstandResult model and its JSON form, never compiler internals.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.application.services.understand import UnderstandTranscriptService
from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import (
    EvaluationReason,
    EvaluationReasonCode,
    InputEvaluation,
    UnderstandResult,
)
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)


def _result(text: str = CANONICAL, run_id: UUID | None = None) -> UnderstandResult:
    transcript = Transcript(
        transcript_id=uuid4(), provider="mock", text=text, created_at=datetime.now(UTC)
    )
    service = UnderstandTranscriptService(compiler=SemanticCompiler(), evaluator=InputEvaluator())
    return service.execute(transcript=transcript, run_id=run_id)


def test_result_round_trips_through_json_for_the_act_side() -> None:
    result = _result(run_id=uuid4())

    decoded = UnderstandResult.model_validate_json(result.model_dump_json())

    assert decoded == result
    assert decoded.actionability is Actionability.PARTIAL


def test_json_payload_exposes_the_handoff_fields() -> None:
    payload = json.loads(_result().model_dump_json())

    assert set(payload) == {
        "result_id",
        "schema_version",
        "run_id",
        "transcript",
        "audio",
        "semantic_state",
        "evaluation",
        "created_at",
    }
    assert payload["schema_version"] == "1.0"
    assert payload["semantic_state"]["schema_version"] == "2.0"
    assert payload["evaluation"]["actionability"] == "PARTIAL"
    assert payload["transcript"]["text"] == CANONICAL
    assert payload["semantic_state"]["negated_actions"] == []


def test_negated_actions_reach_act_separately_from_requested_actions() -> None:
    payload = json.loads(
        _result("Don't dispatch 200 bags of UltraTech cement to Sharma Builders.").model_dump_json()
    )

    assert payload["semantic_state"]["requested_actions"] == []
    assert [a["action_type"] for a in payload["semantic_state"]["negated_actions"]] == ["DISPATCH"]
    assert payload["evaluation"]["actionability"] == "CLARIFICATION_REQUIRED"


def test_result_rejects_state_from_another_transcript() -> None:
    result = _result()
    other = result.transcript.model_copy(update={"transcript_id": uuid4()})

    with pytest.raises(ValidationError, match="not compiled from this transcript"):
        UnderstandResult.model_validate({**result.model_dump(), "transcript": other.model_dump()})


def test_result_rejects_evaluation_of_another_state() -> None:
    result = _result()
    evaluation = result.evaluation.model_dump()
    evaluation["semantic_state_id"] = uuid4()

    with pytest.raises(ValidationError, match="evaluation does not belong"):
        UnderstandResult.model_validate({**result.model_dump(), "evaluation": evaluation})


def test_result_rejects_mismatched_run_ids() -> None:
    result = _result(run_id=uuid4())

    with pytest.raises(ValidationError, match="run_id"):
        UnderstandResult.model_validate({**result.model_dump(), "run_id": uuid4()})


def test_evaluation_actionability_must_match_its_reasons() -> None:
    reason = EvaluationReason(
        code=EvaluationReasonCode.MISSING_CUSTOMER,
        effect=Actionability.CLARIFICATION_REQUIRED,
        message="missing",
    )

    with pytest.raises(ValidationError, match="does not match reasons"):
        InputEvaluation(
            evaluation_id=uuid4(),
            semantic_state_id=uuid4(),
            actionability=Actionability.COMPLETE,
            reasons=[reason],
            evaluator_version="test",
            evaluated_at=datetime.now(UTC),
        )


def test_evaluation_requires_at_least_one_reason() -> None:
    with pytest.raises(ValidationError):
        InputEvaluation(
            evaluation_id=uuid4(),
            semantic_state_id=uuid4(),
            actionability=Actionability.COMPLETE,
            reasons=[],
            evaluator_version="test",
            evaluated_at=datetime.now(UTC),
        )


def test_empty_transcript_text_is_rejected_by_the_transcript_contract() -> None:
    with pytest.raises(ValidationError):
        Transcript(transcript_id=uuid4(), provider="mock", text="", created_at=datetime.now(UTC))
