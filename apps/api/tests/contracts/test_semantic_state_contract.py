from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.domain.schemas.common import (
    Actionability,
    ConfidenceSource,
)
from vaaniflow.domain.schemas.semantic import (
    IntentType,
    RequestedAction,
    RequestedActionType,
    SemanticState,
    Urgency,
)


def test_semantic_state_accepts_valid_contract() -> None:
    transcript_id = uuid4()

    state = SemanticState(
        semantic_state_id=uuid4(),
        intent=IntentType.CREATE_DISPATCH_ORDER,
        intent_confidence={
            "score": 0.96,
            "source": ConfidenceSource.MODEL,
        },
        requested_actions=[
            RequestedAction(
                action_type=RequestedActionType.CREATE_INVOICE_DRAFT,
                explicit=True,
                confidence={
                    "score": 0.94,
                    "source": ConfidenceSource.MODEL,
                },
            ),
            RequestedAction(
                action_type=RequestedActionType.REQUEST_APPROVAL,
                explicit=True,
                confidence={
                    "score": 0.99,
                    "source": ConfidenceSource.RULE,
                },
            ),
        ],
        urgency=Urgency.HIGH,
        actionability=Actionability.PARTIAL,
        source_transcript_id=transcript_id,
        created_at=datetime.now(UTC),
    )

    assert state.intent == IntentType.CREATE_DISPATCH_ORDER
    assert state.actionability == Actionability.PARTIAL
    assert len(state.requested_actions) == 2
    assert state.schema_version == "1.0"
    assert state.version == 1


def test_confidence_score_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        SemanticState(
            semantic_state_id=uuid4(),
            intent=IntentType.UNKNOWN,
            intent_confidence={
                "score": 1.5,
                "source": ConfidenceSource.MODEL,
            },
            actionability=Actionability.BLOCKED,
            source_transcript_id=uuid4(),
            created_at=datetime.now(UTC),
        )


def test_domain_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticState(
            semantic_state_id=uuid4(),
            intent=IntentType.UNKNOWN,
            intent_confidence={
                "score": 0.5,
                "source": ConfidenceSource.MODEL,
            },
            actionability=Actionability.PARTIAL,
            source_transcript_id=uuid4(),
            created_at=datetime.now(UTC),
            totally_fake_field="this must fail",
        )