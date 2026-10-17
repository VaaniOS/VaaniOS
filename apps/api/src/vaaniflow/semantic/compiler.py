import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from vaaniflow.domain.schemas.common import (
    Actionability,
    Confidence,
    ConfidenceSource,
)
from vaaniflow.domain.schemas.semantic import (
    IntentType,
    Quantity,
    RequestedAction,
    RequestedActionType,
    SemanticConstraint,
    SemanticEntity,
    SemanticEntityType,
    SemanticState,
    Urgency,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic.ambiguity import (
    build_missing_field_ambiguities,
    build_temporal_ambiguities,
)
from vaaniflow.semantic.corrections import detect_quantity_corrections
from vaaniflow.semantic.references import extract_references
from vaaniflow.semantic.temporal import extract_temporal_expressions

_QUANTITY_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>"
    r"bags?|bag|"
    r"kg|kgs|kilograms?|"
    r"g|grams?|"
    r"tons?|tonnes?|"
    r"pieces?|pcs?|"
    r"units?"
    r")\b",
    flags=re.IGNORECASE,
)


_CUSTOMER_PATTERN = re.compile(
    r"(?P<name>"
    r"[A-Za-z][A-Za-z0-9&.'-]*(?:\s+[A-Za-z0-9&.'-]+){0,4}"
    r")\s+"
    r"(?:ko|to)\b",
    flags=re.IGNORECASE,
)


_PRODUCT_AFTER_QUANTITY_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s+"
    r"(?:bags?|kg|kgs|kilograms?|g|grams?|tons?|tonnes?|pieces?|pcs?|units?)"
    r"\s+"
    r"(?P<product>"
    r"[A-Za-z][A-Za-z0-9&./-]*"
    r"(?:\s+[A-Za-z0-9&./-]+){0,5}"
    r")",
    flags=re.IGNORECASE,
)


_PRODUCT_EXPLICIT_PATTERN = re.compile(
    r"\b(?:product|item)\s+"
    r"(?P<product>"
    r"[A-Za-z][A-Za-z0-9&./-]*"
    r"(?:\s+[A-Za-z0-9&./-]+){0,5}"
    r")",
    flags=re.IGNORECASE,
)


_PRICE_CONTEXT_PATTERN = re.compile(
    r"(?:rate|price|cost|at)\s+(?:of\s+)?"
    r"(?:₹\s*|rs\.?\s*|rupees?\s*)?"
    r"(?P<price>\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)


_URGENCY_HIGH = (
    "urgent",
    "urgently",
    "immediately",
    "asap",
    "right away",
    "turant",
    "jaldi",
)


_URGENCY_CRITICAL = (
    "critical",
    "emergency",
    "immediate emergency",
)


_PRODUCT_ACTION_STOPWORDS = {
    "dispatch",
    "bhej",
    "bhejo",
    "send",
    "ship",
    "deliver",
    "delivery",
    "invoice",
    "bill",
    "create",
    "karo",
    "kar",
    "banao",
    "make",
}


def _confidence(score: float) -> Confidence:
    return Confidence(
        score=score,
        source=ConfidenceSource.RULE,
    )


def _normalize(text: str) -> str:
    return " ".join(text.strip().split())


def _trim_entity_phrase(value: str) -> str:
    stop_words = (
        " immediately",
        " urgently",
        " asap",
        " and",
        " then",
        " dispatch",
        " bhej",
        " send",
        " ship",
        " deliver",
        " delivery",
        " invoice",
        " bill",
        " rate",
        " price",
        " plus",
        " gst",
        " tomorrow",
        " today",
        " yesterday",
        " parso",
        " kal",
        " ko",
    )

    normalized = _normalize(value)
    lowered = normalized.casefold()

    cut_positions = [
        lowered.find(stop)
        for stop in stop_words
        if lowered.find(stop) != -1
    ]

    if cut_positions:
        normalized = normalized[: min(cut_positions)].strip()

    return normalized


def _is_valid_product_candidate(candidate: str) -> bool:
    normalized = candidate.strip().casefold()

    if not normalized:
        return False

    first_word = normalized.split()[0]

    return first_word not in _PRODUCT_ACTION_STOPWORDS


def _infer_intent(text: str) -> tuple[IntentType, float]:
    lowered = text.casefold()

    # Specific business actions must win over generic verbs such as
    # "send"/"bhej", because sending an invoice for approval is not dispatch.
    if any(
        token in lowered
        for token in (
            "cancel order",
            "cancel the order",
        )
    ):
        return IntentType.CANCEL_ORDER, 0.95

    if any(
        token in lowered
        for token in (
            "update order",
            "change order",
            "modify order",
        )
    ):
        return IntentType.UPDATE_ORDER, 0.94

    if any(
        token in lowered
        for token in (
            "invoice",
            "bill",
            "billing",
            "invoice bana",
            "invoice create",
        )
    ):
        return IntentType.CREATE_INVOICE, 0.95

    if any(
        token in lowered
        for token in (
            "inventory",
            "stock",
            "available quantity",
            "kitna stock",
            "stock kitna",
        )
    ):
        return IntentType.CHECK_INVENTORY, 0.96

    if any(
        token in lowered
        for token in (
            "price",
            "rate",
            "cost",
            "kitne ka",
            "kitna rate",
        )
    ) and not any(
        token in lowered
        for token in (
            "dispatch",
            "dispatch karo",
            "dispatch kar",
        )
    ):
        return IntentType.CHECK_PRICE, 0.94

    if any(
        token in lowered
        for token in (
            "dispatch",
            "dispatch karo",
            "dispatch kar",
            "ship",
            "deliver",
            "delivery",
        )
    ):
        return IntentType.CREATE_DISPATCH_ORDER, 0.96

    if any(
        token in lowered
        for token in (
            "notify",
            "notification",
            "message",
        )
    ):
        return IntentType.SEND_NOTIFICATION, 0.91

    if any(
        token in lowered
        for token in (
            "order",
            "create order",
            "place order",
            "order bana",
        )
    ):
        return IntentType.CREATE_ORDER, 0.94

    return IntentType.UNKNOWN, 0.20


def _extract_customer(text: str) -> SemanticEntity | None:
    match = _CUSTOMER_PATTERN.search(text)

    if match is None:
        return None

    value = _trim_entity_phrase(match.group("name"))

    if not value:
        return None

    return SemanticEntity(
        entity_id=uuid4(),
        entity_type=SemanticEntityType.CUSTOMER,
        surface_text=value,
        normalized_text=value.casefold(),
        confidence=_confidence(0.90),
    )


def _extract_product(text: str) -> SemanticEntity | None:
    match = _PRODUCT_AFTER_QUANTITY_PATTERN.search(text)

    if match is None:
        match = _PRODUCT_EXPLICIT_PATTERN.search(text)

    if match is None:
        return None

    value = _trim_entity_phrase(match.group("product"))

    if not _is_valid_product_candidate(value):
        return None

    if not value:
        return None

    return SemanticEntity(
        entity_id=uuid4(),
        entity_type=SemanticEntityType.PRODUCT,
        surface_text=value,
        normalized_text=value.casefold(),
        confidence=_confidence(0.88),
    )


def _extract_quantities(
    text: str,
) -> tuple[list[Quantity], list[re.Match[str]]]:
    matches = list(_QUANTITY_PATTERN.finditer(text))

    quantities = [
        Quantity(
            value=Decimal(match.group("value")),
            unit=match.group("unit").casefold(),
            confidence=_confidence(0.98),
        )
        for match in matches
    ]

    return quantities, matches


def _extract_price_entity(text: str) -> SemanticEntity | None:
    match = _PRICE_CONTEXT_PATTERN.search(text)

    if match is None:
        return None

    price = match.group("price")

    return SemanticEntity(
        entity_id=uuid4(),
        entity_type=SemanticEntityType.PRICE,
        surface_text=price,
        normalized_text=price,
        confidence=_confidence(0.94),
    )


def _extract_constraints(text: str) -> list[SemanticConstraint]:
    constraints: list[SemanticConstraint] = []

    lowered = text.casefold()

    if "plus gst" in lowered or "including gst" in lowered:
        operator = "ADD" if "plus gst" in lowered else "INCLUDE"

        surface = (
            "plus GST"
            if "plus gst" in lowered
            else "including GST"
        )

        constraints.append(
            SemanticConstraint(
                field="tax",
                operator=operator,
                value="GST",
                surface_text=surface,
                confidence=_confidence(0.96),
            )
        )

    return constraints


def _extract_urgency(text: str) -> Urgency:
    lowered = text.casefold()

    if any(token in lowered for token in _URGENCY_CRITICAL):
        return Urgency.CRITICAL

    if any(token in lowered for token in _URGENCY_HIGH):
        return Urgency.HIGH

    return Urgency.NORMAL


def _extract_requested_actions(
    text: str,
    intent: IntentType,
) -> list[RequestedAction]:
    lowered = text.casefold()
    actions: list[RequestedAction] = []

    def add(
        action_type: RequestedActionType,
        explicit: bool = True,
        score: float = 0.94,
    ) -> None:
        if any(action.action_type == action_type for action in actions):
            return

        actions.append(
            RequestedAction(
                action_type=action_type,
                explicit=explicit,
                confidence=_confidence(score),
            )
        )

    if intent is IntentType.CREATE_ORDER:
        add(RequestedActionType.CREATE_ORDER)

    if intent is IntentType.CREATE_DISPATCH_ORDER:
        add(RequestedActionType.DISPATCH)

    if intent is IntentType.CREATE_INVOICE:
        add(RequestedActionType.CREATE_INVOICE_DRAFT)

    if intent in (
        IntentType.CHECK_INVENTORY,
        IntentType.CHECK_PRICE,
    ):
        add(
            RequestedActionType.CHECK,
            score=0.97,
        )

    if intent is IntentType.SEND_NOTIFICATION:
        add(RequestedActionType.NOTIFY_CUSTOMER)

    if any(
        phrase in lowered
        for phrase in (
            "invoice bana ke approve",
            "invoice bana kar approve",
            "send for approval",
            "approval",
            "approve",
        )
    ):
        add(
            RequestedActionType.REQUEST_APPROVAL,
            score=0.98,
        )

    if any(
        phrase in lowered
        for phrase in (
            "notify",
            "notification",
            "whatsapp pe bhej",
            "whatsapp me bhej",
        )
    ):
        add(RequestedActionType.NOTIFY_CUSTOMER)

    return actions


def _determine_actionability(
    intent: IntentType,
    ambiguities: list,
) -> Actionability:
    if intent is IntentType.UNKNOWN:
        return Actionability.BLOCKED

    if ambiguities:
        return Actionability.CLARIFICATION_REQUIRED

    return Actionability.COMPLETE


class SemanticCompiler:
    """
    Deterministic baseline semantic compiler.

    Input:
        Transcript

    Output:
        SemanticState

    This component understands language only. It does not:
    - resolve business IDs
    - query business databases
    - validate prices
    - inspect inventory
    - authorize actions
    - execute tools
    """

    def compile(self, transcript: Transcript) -> SemanticState:
        text = _normalize(transcript.text)

        intent, intent_score = _infer_intent(text)

        customer = _extract_customer(text)
        product = _extract_product(text)

        quantities, quantity_matches = _extract_quantities(text)

        corrections = detect_quantity_corrections(
            text,
            quantity_matches,
        )

        if corrections:
            corrected = corrections[-1].corrected_value

            quantities = [
                Quantity(
                    value=Decimal(str(corrected["value"])),
                    unit=str(corrected["unit"]),
                    confidence=_confidence(0.99),
                )
            ]

        entities: list[SemanticEntity] = []

        if customer is not None:
            entities.append(customer)

        if product is not None:
            entities.append(product)

        price_entity = _extract_price_entity(text)

        if price_entity is not None:
            entities.append(price_entity)

        references = extract_references(text)

        temporal_expressions = extract_temporal_expressions(text)

        ambiguous_dates = [
            expression.surface_text
            for expression in temporal_expressions
            if expression.resolution_status.value == "AMBIGUOUS"
        ]

        ambiguities = build_temporal_ambiguities(
            ambiguous_dates,
        )

        ambiguities.extend(
            build_missing_field_ambiguities(
                intent,
                has_customer=customer is not None,
                has_product=product is not None,
                has_quantity=bool(quantities),
            )
        )

        requested_actions = _extract_requested_actions(
            text,
            intent,
        )

        constraints = _extract_constraints(text)

        actionability = _determine_actionability(
            intent,
            ambiguities,
        )

        return SemanticState(
            semantic_state_id=uuid4(),
            intent=intent,
            intent_confidence=_confidence(intent_score),
            entities=entities,
            quantities=quantities,
            temporal_expressions=temporal_expressions,
            references=references,
            constraints=constraints,
            corrections=corrections,
            ambiguities=ambiguities,
            requested_actions=requested_actions,
            urgency=_extract_urgency(text),
            actionability=actionability,
            source_transcript_id=transcript.transcript_id,
            created_at=datetime.now(UTC),
        )