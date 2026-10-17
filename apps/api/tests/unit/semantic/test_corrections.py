from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic.compiler import SemanticCompiler


def test_quantity_correction_preserves_superseded_value() -> None:
    transcript = Transcript(
        transcript_id=uuid4(),
        provider="test",
        text="Send 200 bags, actually 220 bags.",
        created_at=datetime.now(UTC),
    )

    state = SemanticCompiler().compile(transcript)

    assert len(state.corrections) == 1

    correction = state.corrections[0]

    assert correction.field == "quantity"
    assert correction.previous_value["value"] == 200
    assert correction.corrected_value["value"] == 220

    # Final semantic quantity must be the corrected value.
    assert len(state.quantities) == 1
    assert state.quantities[0].value == 220