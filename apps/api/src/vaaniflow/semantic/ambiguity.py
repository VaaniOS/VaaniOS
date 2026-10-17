"""
Semantic ambiguity construction (System-Design 05 §5.7).

Only ambiguity visible in the language itself is produced here. Whether
"Sharma Builders" matches one or several customer records is a
business-context ambiguity owned by context resolution.

Missing required information is not an ambiguity: Input Evaluation reports
it as a MISSING_* reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

from vaaniflow.domain.schemas.common import AmbiguitySeverity
from vaaniflow.domain.schemas.semantic import (
    Ambiguity,
    AmbiguityType,
    RequestedActionType,
    SemanticSlot,
    TemporalExpression,
    TemporalResolutionStatus,
    TemporalTarget,
)


def _ambiguity(
    ambiguity_type: AmbiguityType,
    slot: SemanticSlot,
    description: str,
    severity: AmbiguitySeverity,
    *,
    candidates: Sequence[str] = (),
    related_ids: Sequence[UUID] = (),
    requires_clarification: bool = True,
) -> Ambiguity:
    return Ambiguity(
        ambiguity_id=uuid4(),
        ambiguity_type=ambiguity_type,
        slot=slot,
        description=description,
        candidates=list(candidates),
        related_ids=list(related_ids),
        severity=severity,
        requires_clarification=requires_clarification,
    )


def competing_customers(candidates: Sequence[str]) -> Ambiguity:
    return _ambiguity(
        AmbiguityType.ENTITY_AMBIGUITY,
        SemanticSlot.CUSTOMER,
        "Several different customers were named without a correction.",
        AmbiguitySeverity.HIGH,
        candidates=candidates,
    )


def conflicting_quantities(product: str, candidates: Sequence[str], item_id: UUID) -> Ambiguity:
    return _ambiguity(
        AmbiguityType.VALUE_AMBIGUITY,
        SemanticSlot.QUANTITY,
        f"Conflicting quantities were stated for '{product}' without a correction.",
        AmbiguitySeverity.HIGH,
        candidates=candidates,
        related_ids=[item_id],
    )


def conflicting_prices(candidates: Sequence[str], price_ids: Sequence[UUID]) -> Ambiguity:
    return _ambiguity(
        AmbiguityType.VALUE_AMBIGUITY,
        SemanticSlot.PRICE,
        "Several different prices were stated for the same item without a correction.",
        AmbiguitySeverity.HIGH,
        candidates=candidates,
        related_ids=price_ids,
    )


def unscoped_price(price_surface: str, price_id: UUID, item_ids: Sequence[UUID]) -> Ambiguity:
    return _ambiguity(
        AmbiguityType.SCOPE_AMBIGUITY,
        SemanticSlot.PRICE,
        f"The price '{price_surface}' could apply to more than one item.",
        AmbiguitySeverity.HIGH,
        candidates=[],
        related_ids=[price_id, *item_ids],
    )


def competing_actions(actions: Sequence[RequestedActionType]) -> Ambiguity:
    return _ambiguity(
        AmbiguityType.ACTION_AMBIGUITY,
        SemanticSlot.ACTION,
        "The request both modifies/cancels an order and creates new work.",
        AmbiguitySeverity.HIGH,
        candidates=[action.value for action in actions],
    )


def temporal_ambiguities(expressions: Sequence[TemporalExpression]) -> list[Ambiguity]:
    ambiguities: list[Ambiguity] = []
    for expression in expressions:
        if expression.resolution_status is not TemporalResolutionStatus.AMBIGUOUS:
            continue
        magnitude = expression.normalized_expression.removeprefix("DAY_OFFSET:±")
        ambiguities.append(
            _ambiguity(
                AmbiguityType.TEMPORAL_AMBIGUITY,
                SemanticSlot.DATE,
                (
                    f"'{expression.surface_text}' can mean {magnitude} day(s) before or "
                    "after today and no tense evidence disambiguates it."
                ),
                AmbiguitySeverity.HIGH
                if expression.target is not TemporalTarget.UNSPECIFIED
                else AmbiguitySeverity.MEDIUM,
                candidates=[f"DAY_OFFSET:-{magnitude}", f"DAY_OFFSET:+{magnitude}"],
                related_ids=[expression.expression_id],
            )
        )
    return ambiguities
