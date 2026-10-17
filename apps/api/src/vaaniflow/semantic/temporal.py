import re
from uuid import uuid4

from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    TemporalExpression,
    TemporalResolutionStatus,
)

_TEMPORAL_PATTERNS: tuple[tuple[str, str, TemporalResolutionStatus, float], ...] = (
    (
        r"\bday after tomorrow\b",
        "DAY_OFFSET:+2",
        TemporalResolutionStatus.UNRESOLVED,
        0.98,
    ),
    (
        r"\bday before yesterday\b",
        "DAY_OFFSET:-2",
        TemporalResolutionStatus.UNRESOLVED,
        0.98,
    ),
    (
        r"\btomorrow\b",
        "DAY_OFFSET:+1",
        TemporalResolutionStatus.UNRESOLVED,
        0.99,
    ),
    (
        r"\byesterday\b",
        "DAY_OFFSET:-1",
        TemporalResolutionStatus.UNRESOLVED,
        0.99,
    ),
    (
        r"\btoday\b",
        "DAY_OFFSET:0",
        TemporalResolutionStatus.UNRESOLVED,
        0.99,
    ),
    (
        r"\bparso\b",
        "PARSO_RELATIVE",
        TemporalResolutionStatus.AMBIGUOUS,
        0.82,
    ),
    (
        r"\bkal\b",
        "KAL_RELATIVE",
        TemporalResolutionStatus.AMBIGUOUS,
        0.78,
    ),
)


def _confidence(score: float) -> Confidence:
    return Confidence(
        score=score,
        source=ConfidenceSource.RULE,
    )


def extract_temporal_expressions(text: str) -> list[TemporalExpression]:
    """
    Extract temporal language without resolving it to a business date.

    Examples:
        "tomorrow" -> DAY_OFFSET:+1
        "yesterday" -> DAY_OFFSET:-1
        "parso" -> PARSO_RELATIVE / AMBIGUOUS
        "kal" -> KAL_RELATIVE / AMBIGUOUS
    """
    expressions: list[TemporalExpression] = []

    for pattern, normalized, status, score in _TEMPORAL_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            surface = match.group(0)

            expressions.append(
                TemporalExpression(
                    expression_id=uuid4(),
                    surface_text=surface,
                    normalized_expression=normalized,
                    resolved_datetime=None,
                    resolution_status=status,
                    confidence=_confidence(score),
                )
            )

    return expressions