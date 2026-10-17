"""
SemanticState — the typed intermediate representation produced by the
semantic compiler (System-Design 05, ADR-002, ADR-015).

The compiler understands language only. Nothing in this module may carry
business identifiers (customer IDs, SKUs, quote IDs, order IDs, inventory,
invoice numbers) or resolved calendar dates. Those are produced downstream by
context resolution and attached to separate context models.

All character spans are offsets into the source ``Transcript.text``.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from vaaniflow.domain.schemas.common import (
    AmbiguitySeverity,
    Confidence,
    DomainSchema,
)

SEMANTIC_SCHEMA_VERSION = "2.0"


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
    DISPATCH = "DISPATCH"
    CREATE_INVOICE_DRAFT = "CREATE_INVOICE_DRAFT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    SEND_NOTIFICATION = "SEND_NOTIFICATION"
    CANCEL_ORDER = "CANCEL_ORDER"
    UPDATE_ORDER = "UPDATE_ORDER"
    CHECK_INVENTORY = "CHECK_INVENTORY"
    CHECK_PRICE = "CHECK_PRICE"


class ActionParty(StrEnum):
    """Who an action is directed at, as expressed in language."""

    SPEAKER = "SPEAKER"
    CUSTOMER = "CUSTOMER"
    ADDRESSEE = "ADDRESSEE"
    UNSPECIFIED = "UNSPECIFIED"


class SemanticSlot(StrEnum):
    """Semantic fields that references, ambiguities and reasons can target."""

    INTENT = "INTENT"
    ACTION = "ACTION"
    CUSTOMER = "CUSTOMER"
    ITEM = "ITEM"
    PRODUCT = "PRODUCT"
    QUANTITY = "QUANTITY"
    UNIT = "UNIT"
    PRICE = "PRICE"
    TAX = "TAX"
    QUOTE = "QUOTE"
    ORDER = "ORDER"
    DATE = "DATE"
    UNKNOWN = "UNKNOWN"


class SemanticEntityType(StrEnum):
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    PERSON = "PERSON"


class ReferenceType(StrEnum):
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    HISTORICAL_PRICE = "HISTORICAL_PRICE"
    HISTORICAL_QUOTE = "HISTORICAL_QUOTE"
    ORDER = "ORDER"
    PREVIOUS_VALUE = "PREVIOUS_VALUE"
    PRONOUN = "PRONOUN"


class TemporalKind(StrEnum):
    RELATIVE_DAY = "RELATIVE_DAY"
    RELATIVE_WEEK = "RELATIVE_WEEK"
    WEEKDAY = "WEEKDAY"
    EXPLICIT_DATE = "EXPLICIT_DATE"


class TemporalDirection(StrEnum):
    PAST = "PAST"
    PRESENT = "PRESENT"
    FUTURE = "FUTURE"
    UNKNOWN = "UNKNOWN"


class TemporalTarget(StrEnum):
    """What a temporal expression qualifies."""

    EXECUTION = "EXECUTION"
    REFERENCE = "REFERENCE"
    UNSPECIFIED = "UNSPECIFIED"


class TemporalResolutionStatus(StrEnum):
    """
    UNRESOLVED: linguistically determined; needs the run clock, business
        timezone and calendar (context layer) to become a date.
    AMBIGUOUS: the language itself admits several readings (e.g. "parso"
        without tense evidence).
    ABSOLUTE: a fully specified calendar date was spoken.
    """

    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    ABSOLUTE = "ABSOLUTE"


class Weekday(StrEnum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class PriceSource(StrEnum):
    SPOKEN = "SPOKEN"
    HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"
    SPOKEN_WITH_HISTORICAL_REFERENCE = "SPOKEN_WITH_HISTORICAL_REFERENCE"


class TaxTreatment(StrEnum):
    EXCLUSIVE = "EXCLUSIVE"
    INCLUSIVE = "INCLUSIVE"
    UNSPECIFIED = "UNSPECIFIED"


class CorrectionField(StrEnum):
    QUANTITY = "QUANTITY"
    UNIT = "UNIT"
    PRICE = "PRICE"
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    DATE = "DATE"


class AmbiguityType(StrEnum):
    """Semantic ambiguity classes (System-Design 05 §5.7).

    Business-context ambiguity (e.g. two customer records matching one name)
    is NOT represented here; it belongs to context resolution
    (``vaaniflow.context.models.resolution``).
    """

    ENTITY_AMBIGUITY = "ENTITY_AMBIGUITY"
    VALUE_AMBIGUITY = "VALUE_AMBIGUITY"
    TEMPORAL_AMBIGUITY = "TEMPORAL_AMBIGUITY"
    ACTION_AMBIGUITY = "ACTION_AMBIGUITY"
    REFERENCE_AMBIGUITY = "REFERENCE_AMBIGUITY"
    SCOPE_AMBIGUITY = "SCOPE_AMBIGUITY"


class Urgency(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TextSpan(DomainSchema):
    """Half-open character range ``[start, end)`` in the transcript text."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        return self


class SemanticEntity(DomainSchema):
    """A named mention (customer, product, person) as spoken. Never an ID."""

    entity_id: UUID
    entity_type: SemanticEntityType
    surface_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    span: TextSpan
    confidence: Confidence


class SemanticQuantity(DomainSchema):
    value: Decimal = Field(gt=0)
    unit: str | None = Field(default=None, min_length=1)
    surface_text: str = Field(min_length=1)
    span: TextSpan
    confidence: Confidence


class SemanticItem(DomainSchema):
    """One requested line: a product mention bound to its quantity."""

    item_id: UUID
    product: SemanticEntity | None = None
    quantity: SemanticQuantity | None = None

    @model_validator(mode="after")
    def _check_item(self) -> Self:
        if self.product is None and self.quantity is None:
            raise ValueError("an item needs a product or a quantity")
        if self.product is not None and self.product.entity_type is not SemanticEntityType.PRODUCT:
            raise ValueError("item product must be a PRODUCT entity")
        return self


class SemanticPrice(DomainSchema):
    """
    A price as expressed by the user. A spoken amount is a claim to be
    validated downstream, never an authoritative business price.
    """

    price_id: UUID
    source: PriceSource
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=1)
    per_unit: str | None = Field(default=None, min_length=1)
    item_id: UUID | None = None
    reference_id: UUID | None = None
    surface_text: str = Field(min_length=1)
    span: TextSpan
    confidence: Confidence

    @model_validator(mode="after")
    def _check_source(self) -> Self:
        has_amount = self.amount is not None
        has_reference = self.reference_id is not None
        expected = {
            PriceSource.SPOKEN: (True, False),
            PriceSource.HISTORICAL_REFERENCE: (False, True),
            PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE: (True, True),
        }[self.source]
        if (has_amount, has_reference) != expected:
            raise ValueError(f"price source {self.source} is inconsistent with amount/reference")
        return self


class TaxInstruction(DomainSchema):
    """A spoken tax instruction such as "plus GST". Never a computed amount."""

    tax_type: str = Field(min_length=1)
    treatment: TaxTreatment
    surface_text: str = Field(min_length=1)
    span: TextSpan
    confidence: Confidence


class SemanticReference(DomainSchema):
    """
    A reference such as "same rate", "previous quote", "that order" or "it".
    Extraction only: resolution against business data happens downstream.
    """

    reference_id: UUID
    reference_type: ReferenceType
    target_slot: SemanticSlot
    surface_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    span: TextSpan
    item_id: UUID | None = None
    temporal_expression_id: UUID | None = None
    confidence: Confidence


class TemporalExpression(DomainSchema):
    """
    A temporal expression as spoken, normalised linguistically but never
    resolved to a calendar date (System-Design 06 §6.5, ADR-014).
    """

    expression_id: UUID
    surface_text: str = Field(min_length=1)
    span: TextSpan
    kind: TemporalKind
    normalized_expression: str = Field(min_length=1)
    direction: TemporalDirection
    day_offset: int | None = None
    week_offset: int | None = None
    weekday: Weekday | None = None
    day: int | None = Field(default=None, ge=1, le=31)
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=1900)
    target: TemporalTarget = TemporalTarget.UNSPECIFIED
    resolution_status: TemporalResolutionStatus
    direction_evidence: str | None = None
    confidence: Confidence

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if (
            self.resolution_status is TemporalResolutionStatus.AMBIGUOUS
            and self.day_offset is not None
        ):
            raise ValueError("ambiguous expressions must not carry a day offset")
        if self.kind is TemporalKind.RELATIVE_DAY and (
            self.resolution_status is TemporalResolutionStatus.UNRESOLVED
            and self.day_offset is None
        ):
            raise ValueError("unambiguous relative days need a day offset")
        if self.kind is TemporalKind.WEEKDAY and self.weekday is None:
            raise ValueError("weekday expressions need a weekday")
        if self.kind is TemporalKind.EXPLICIT_DATE and (self.day is None or self.month is None):
            raise ValueError("explicit dates need day and month")
        if self.resolution_status is TemporalResolutionStatus.ABSOLUTE and self.year is None:
            raise ValueError("absolute dates need a year")
        return self


class CorrectionValue(DomainSchema):
    surface_text: str = Field(min_length=1)
    normalized: str = Field(min_length=1)
    amount: Decimal | None = None
    unit: str | None = None
    span: TextSpan


class CorrectionEvent(DomainSchema):
    """
    An explicit self-correction ("200 — actually 220"). The superseded value
    is preserved here; the current state only carries the corrected value
    (ADR-012).
    """

    correction_id: UUID
    field: CorrectionField
    previous_value: CorrectionValue
    corrected_value: CorrectionValue
    marker: str = Field(min_length=1)
    target_id: UUID | None = None
    source_text: str = Field(min_length=1)
    confidence: Confidence


class Ambiguity(DomainSchema):
    """An unresolved *semantic* ambiguity detected in the utterance."""

    ambiguity_id: UUID
    ambiguity_type: AmbiguityType
    slot: SemanticSlot
    description: str = Field(min_length=1)
    candidates: list[str] = Field(default_factory=list)
    related_ids: list[UUID] = Field(default_factory=list)
    severity: AmbiguitySeverity
    requires_clarification: bool = True


class RequestedAction(DomainSchema):
    action_id: UUID
    action_type: RequestedActionType
    explicit: bool
    recipient: ActionParty | None = None
    channel: str | None = Field(default=None, min_length=1)
    surface_text: str = Field(min_length=1)
    span: TextSpan
    confidence: Confidence


class CompilerProvenance(DomainSchema):
    compiler_name: str = Field(min_length=1)
    compiler_version: str = Field(min_length=1)


class SemanticState(DomainSchema):
    """
    Versioned intermediate representation between ASR and business-agent
    execution (ADR-002).

    Actionability is not part of this object: it is assessed by Input
    Evaluation and travels next to the state in ``UnderstandResult``
    (ADR-013).
    """

    semantic_state_id: UUID
    schema_version: Literal["2.0"] = "2.0"
    version: int = Field(default=1, ge=1)

    run_id: UUID | None = None
    source_transcript_id: UUID
    compiler: CompilerProvenance

    intent: IntentType
    intent_confidence: Confidence

    customer: SemanticEntity | None = None
    addressee: SemanticEntity | None = None

    items: list[SemanticItem] = Field(default_factory=list)
    pricing: list[SemanticPrice] = Field(default_factory=list)
    tax: TaxInstruction | None = None

    references: list[SemanticReference] = Field(default_factory=list)
    temporal_expressions: list[TemporalExpression] = Field(default_factory=list)
    corrections: list[CorrectionEvent] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    requested_actions: list[RequestedAction] = Field(default_factory=list)

    # Actions the user explicitly told NOT to perform ("don't dispatch",
    # "dispatch mat karo"). They are never requested actions and must never
    # be executed; Input Evaluation makes the request non-actionable (ADR-018).
    negated_actions: list[RequestedAction] = Field(default_factory=list)

    urgency: Urgency = Urgency.NORMAL

    created_at: datetime

    @model_validator(mode="after")
    def _check_links(self) -> Self:
        if (
            self.customer is not None
            and self.customer.entity_type is not SemanticEntityType.CUSTOMER
        ):
            raise ValueError("customer must be a CUSTOMER entity")
        if (
            self.addressee is not None
            and self.addressee.entity_type is not SemanticEntityType.PERSON
        ):
            raise ValueError("addressee must be a PERSON entity")

        item_ids = {item.item_id for item in self.items}
        reference_ids = {reference.reference_id for reference in self.references}
        temporal_ids = {expression.expression_id for expression in self.temporal_expressions}

        if len(item_ids) != len(self.items):
            raise ValueError("item ids must be unique")

        for price in self.pricing:
            if price.item_id is not None and price.item_id not in item_ids:
                raise ValueError("price references an unknown item")
            if price.reference_id is not None and price.reference_id not in reference_ids:
                raise ValueError("price references an unknown reference")

        for reference in self.references:
            if reference.item_id is not None and reference.item_id not in item_ids:
                raise ValueError("reference points to an unknown item")
            if (
                reference.temporal_expression_id is not None
                and reference.temporal_expression_id not in temporal_ids
            ):
                raise ValueError("reference points to an unknown temporal expression")

        return self
