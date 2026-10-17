import re
from decimal import Decimal
from uuid import uuid4

from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import CorrectionEvent

_CORRECTION_MARKERS = (
    "actually",
    "rather",
    "no",
    "sorry",
    "i mean",
    "make that",
    "change that",
)


def _confidence(score: float) -> Confidence:
    return Confidence(
        score=score,
        source=ConfidenceSource.RULE,
    )


def detect_quantity_corrections(
    text: str,
    quantity_matches: list[re.Match[str]],
) -> list[CorrectionEvent]:
    """
    Detect explicit quantity corrections.

    Example:
        "Send 200, actually 220 bags."

    Produces:
        previous_value = 200
        corrected_value = 220
    """
    if len(quantity_matches) < 2:
        return []

    lowered = text.casefold()

    marker_position = min(
        (
            lowered.find(marker)
            for marker in _CORRECTION_MARKERS
            if lowered.find(marker) != -1
        ),
        default=-1,
    )

    if marker_position == -1:
        return []

    before = [
        match
        for match in quantity_matches
        if match.start() < marker_position
    ]
    after = [
        match
        for match in quantity_matches
        if match.start() > marker_position
    ]

    if not before or not after:
        return []

    previous_match = before[-1]
    corrected_match = after[0]

    previous_value = Decimal(previous_match.group("value"))
    corrected_value = Decimal(corrected_match.group("value"))

    unit = corrected_match.group("unit")

    source_start = previous_match.start()
    source_end = corrected_match.end()

    return [
        CorrectionEvent(
            correction_id=uuid4(),
            field="quantity",
            previous_value={
                "value": previous_value,
                "unit": previous_match.group("unit"),
            },
            corrected_value={
                "value": corrected_value,
                "unit": unit,
            },
            reason="Explicit spoken correction.",
            source_text=text[source_start:source_end],
            confidence=_confidence(0.97),
        )
    ]