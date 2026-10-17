from uuid import uuid4

from vaaniflow.domain.schemas.common import AmbiguitySeverity
from vaaniflow.domain.schemas.semantic import (
    Ambiguity,
    AmbiguityType,
    IntentType,
)

_REQUIRED_FIELDS: dict[IntentType, tuple[str, ...]] = {
    IntentType.CREATE_ORDER: (
        "customer",
        "product",
        "quantity",
    ),
    IntentType.CREATE_DISPATCH_ORDER: (
        "customer",
        "product",
        "quantity",
    ),
    IntentType.CREATE_INVOICE: (
        "customer",
        "product",
        "quantity",
    ),
    IntentType.CHECK_INVENTORY: (
        "product",
    ),
    IntentType.CHECK_PRICE: (
        "product",
    ),
}


def build_missing_field_ambiguities(
    intent: IntentType,
    *,
    has_customer: bool,
    has_product: bool,
    has_quantity: bool,
) -> list[Ambiguity]:
    """
    Determine whether the semantic request is missing fields required to
    interpret the selected intent.

    This is semantic completeness only.

    It does NOT validate:
    - whether the customer exists
    - whether the product exists
    - inventory
    - price
    - authorization
    """
    present = {
        "customer": has_customer,
        "product": has_product,
        "quantity": has_quantity,
    }

    ambiguities: list[Ambiguity] = []

    for field in _REQUIRED_FIELDS.get(intent, ()):
        if present.get(field, False):
            continue

        ambiguities.append(
            Ambiguity(
                ambiguity_id=uuid4(),
                ambiguity_type=AmbiguityType.MISSING_REQUIRED_FIELD,
                field=field,
                description=f"Required semantic field '{field}' was not found.",
                candidates=[],
                severity=AmbiguitySeverity.HIGH,
                requires_clarification=True,
            )
        )

    return ambiguities


def build_temporal_ambiguities(
    ambiguous_expressions: list[str],
) -> list[Ambiguity]:
    return [
        Ambiguity(
            ambiguity_id=uuid4(),
            ambiguity_type=AmbiguityType.AMBIGUOUS_DATE,
            field="date",
            description=(
                f"Temporal expression '{expression}' has multiple plausible "
                "relative interpretations."
            ),
            candidates=[],
            severity=AmbiguitySeverity.MEDIUM,
            requires_clarification=True,
        )
        for expression in ambiguous_expressions
    ]