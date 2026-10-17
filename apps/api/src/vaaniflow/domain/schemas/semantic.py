from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import (
    Actionability,
    AmbiguitySeverity,
    Confidence,
    DomainSchema,
)


class IntentType(StrEnum):
    CREATE_ORDER = "CREATE_ORDER"
    CREATE_DISPATCH_ORDER = "CREATE_DISPATCH_ORDER"
    CREATE_INVOICE = "CREATE_INVOICE"
    CHECK_INVENTORY = "CHECK_INVENTORY"
    CHECK_PRICE = "CHECK_PRICE"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"
    UPDATE_ORDER = "UPDATE_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    UNKNOWN = "UNKNOWN"


class RequestedActionType(StrEnum):
    CREATE_ORDER = "CREATE_ORDER"
    CREATE_INVOICE_DRAFT = "CREATE_INVOICE_DRAFT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    DISPATCH = "DISPATCH"
    NOTIFY_CUSTOMER = "NOTIFY_CUSTOMER"
    CHECK = "CHECK"


class AmbiguityType(StrEnum):
    AMBIGUOUS_CUSTOMER = "AMBIGUOUS_CUSTOMER"
    AMBIGUOUS_PRODUCT = "AMBIGUOUS_PRODUCT"
    AMBIGUOUS_QUOTE = "AMBIGUOUS_QUOTE"
    AMBIGUOUS_DATE = "AMBIGUOUS_DATE"
    AMBIGUOUS_QUANTITY = "AMBIGUOUS_QUANTITY"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    CONFLICTING_REFERENCE = "CONFLICTING_REFERENCE"
    OTHER = "OTHER"


class SemanticEntityType(StrEnum):
    CUSTOMER = "CUSTOMER"
    PERSON = "PERSON"
    PRODUCT = "PRODUCT"
    QUANTITY = "QUANTITY"
    UNIT = "UNIT"
    PRICE = "PRICE"
    DATE = "DATE"
    LOCATION = "LOCATION"
    OTHER = "OTHER"


class ReferenceType(StrEnum):
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    HISTORICAL_PRICE = "HISTORICAL_PRICE"
    HISTORICAL_QUOTE = "HISTORICAL_QUOTE"
    RELATIVE_DATE = "RELATIVE_DATE"
    PREVIOUS_VALUE = "PREVIOUS_VALUE"
    OTHER = "OTHER"


class TemporalResolutionStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


class Urgency(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SemanticEntity(DomainSchema):
    """
    An entity extracted from the user's language.

    The semantic compiler does not invent business IDs. Entity resolution
    happens later using business context.
    """

    entity_id: UUID

    entity_type: SemanticEntityType

    surface_text: str = Field(min_length=1)
    normalized_text: str | None = None

    confidence: Confidence

    reference_id: UUID | None = None


class Quantity(DomainSchema):
    value: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)

    confidence: Confidence


class SemanticReference(DomainSchema):
    """
    A reference such as:
    - "same customer"
    - "usual rate"
    - "parso"
    - "previous quote"

    Resolution is deliberately represented separately from extraction.
    """

    reference_id: UUID

    reference_type: ReferenceType

    surface_text: str = Field(min_length=1)
    normalized_text: str | None = None

    confidence: Confidence


class TemporalExpression(DomainSchema):
    """
    Raw temporal expression extracted from speech.

    The semantic compiler may normalize the expression, but actual business
    date resolution belongs to the context/time-resolution layer.
    """

    expression_id: UUID

    surface_text: str = Field(min_length=1)
    normalized_expression: str | None = None

    resolved_datetime: datetime | None = None
    resolution_status: TemporalResolutionStatus

    confidence: Confidence


class SemanticConstraint(DomainSchema):
    """A constraint extracted from the user's request."""

    field: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    value: Any

    surface_text: str | None = None
    confidence: Confidence


class CorrectionEvent(DomainSchema):
    """
    Represents an explicit correction made within the user's speech.

    Example:
        "Send 200... actually 220 bags."

    The correction is represented as an event rather than silently
    overwriting the original value.
    """

    correction_id: UUID

    field: str = Field(min_length=1)

    previous_value: Any
    corrected_value: Any

    reason: str | None = None
    source_text: str = Field(min_length=1)

    confidence: Confidence


class Ambiguity(DomainSchema):
    """An unresolved ambiguity detected by the semantic compiler."""

    ambiguity_id: UUID

    ambiguity_type: AmbiguityType

    field: str | None = None

    description: str = Field(min_length=1)

    candidates: list[Any] = Field(default_factory=list)

    severity: AmbiguitySeverity

    requires_clarification: bool = True


class RequestedAction(DomainSchema):
    """An action explicitly or implicitly requested by the user."""

    action_type: RequestedActionType

    explicit: bool

    confidence: Confidence


class SemanticState(DomainSchema):
    """
    Versioned intermediate representation between ASR and business-agent
    execution.

    This is the contract that separates:
        speech understanding
    from:
        business context + validation + policy + execution.
    """

    semantic_state_id: UUID

    schema_version: str = "1.0"

    version: int = Field(default=1, ge=1)

    intent: IntentType
    intent_confidence: Confidence

    entities: list[SemanticEntity] = Field(default_factory=list)

    quantities: list[Quantity] = Field(default_factory=list)

    temporal_expressions: list[TemporalExpression] = Field(
        default_factory=list
    )

    references: list[SemanticReference] = Field(
        default_factory=list
    )

    constraints: list[SemanticConstraint] = Field(
        default_factory=list
    )

    corrections: list[CorrectionEvent] = Field(
        default_factory=list
    )

    ambiguities: list[Ambiguity] = Field(
        default_factory=list
    )

    requested_actions: list[RequestedAction] = Field(
        default_factory=list
    )

    urgency: Urgency = Urgency.NORMAL

    actionability: Actionability

    source_transcript_id: UUID

    created_at: datetime