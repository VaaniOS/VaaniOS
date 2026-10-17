from uuid import uuid4

from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    ReferenceType,
    SemanticReference,
)

_REFERENCE_PATTERNS: tuple[
    tuple[tuple[str, ...], ReferenceType, str, float], ...
] = (
    (
        ("same customer", "that customer", "the same client"),
        ReferenceType.CUSTOMER,
        "same_customer",
        0.97,
    ),
    (
        ("same product", "that product", "the same item"),
        ReferenceType.PRODUCT,
        "same_product",
        0.97,
    ),
    (
        (
            "same rate",
            "usual rate",
            "usual price",
            "same price",
            "rate we discussed",
            "price we discussed",
            "rate discussed earlier",
            "price discussed earlier",
        ),
        ReferenceType.HISTORICAL_PRICE,
        "historical_price",
        0.96,
    ),
    (
        (
            "previous quote",
            "last quote",
            "earlier quote",
            "old quote",
            "previous quotation",
        ),
        ReferenceType.HISTORICAL_QUOTE,
        "previous_quote",
        0.97,
    ),
    (
        ("previous value", "earlier value", "the earlier number"),
        ReferenceType.PREVIOUS_VALUE,
        "previous_value",
        0.94,
    ),
)


def _confidence(score: float) -> Confidence:
    return Confidence(
        score=score,
        source=ConfidenceSource.RULE,
    )


def extract_references(text: str) -> list[SemanticReference]:
    references: list[SemanticReference] = []
    lowered = text.casefold()

    for patterns, reference_type, normalized, score in _REFERENCE_PATTERNS:
        for pattern in patterns:
            start = lowered.find(pattern)

            if start == -1:
                continue

            surface = text[start : start + len(pattern)]

            references.append(
                SemanticReference(
                    reference_id=uuid4(),
                    reference_type=reference_type,
                    surface_text=surface,
                    normalized_text=normalized,
                    confidence=_confidence(score),
                )
            )

    relative_dates = (
        "today",
        "tomorrow",
        "yesterday",
        "day after tomorrow",
        "day before yesterday",
        "parso",
        "kal",
    )

    for phrase in relative_dates:
        start = lowered.find(phrase)

        if start == -1:
            continue

        surface = text[start : start + len(phrase)]

        references.append(
            SemanticReference(
                reference_id=uuid4(),
                reference_type=ReferenceType.RELATIVE_DATE,
                surface_text=surface,
                normalized_text=phrase.casefold(),
                confidence=_confidence(
                    0.90 if phrase not in {"parso", "kal"} else 0.82
                ),
            )
        )

    return references