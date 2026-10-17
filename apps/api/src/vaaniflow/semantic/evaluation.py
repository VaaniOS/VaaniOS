"""
Input Evaluation (ADR-013): SemanticState → InputEvaluation.

The compiler extracts; the evaluator judges whether what was extracted is a
sufficiently specified, coherent, actionable request. It never re-parses
text and never consults business data.

    COMPLETE                every required slot is stated and coherent
    PARTIAL                 understood, but a reference ("same rate",
                            "that order", "it") must be resolved by context
    CLARIFICATION_REQUIRED  the user must supply or disambiguate something
    BLOCKED                 not an actionable request

Each classification is backed by structured reasons; the overall
actionability is the most restrictive reason effect.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import Actionability, AudioQualityLevel
from vaaniflow.domain.schemas.semantic import (
    IntentType,
    ReferenceType,
    SemanticItem,
    SemanticSlot,
    SemanticState,
    TemporalKind,
    TemporalResolutionStatus,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import (
    EvaluationReason,
    EvaluationReasonCode,
    InputEvaluation,
    most_restrictive,
)
from vaaniflow.semantic.confidence import LOW_CONFIDENCE_THRESHOLD

EVALUATOR_VERSION = "vaaniflow.input-evaluator/1.0.0"

_LINE_ITEM_INTENTS = frozenset({IntentType.CREATE_DISPATCH_ORDER, IntentType.CREATE_ORDER})
_ORDER_TARGET_INTENTS = frozenset({IntentType.CANCEL_ORDER, IntentType.UPDATE_ORDER})
_PRODUCT_INTENTS = frozenset({IntentType.CHECK_INVENTORY, IntentType.CHECK_PRICE})
_CONTEXTUAL_ITEM_REFERENCES = frozenset(
    {ReferenceType.PRONOUN, ReferenceType.ORDER, ReferenceType.PREVIOUS_VALUE}
)

C = Actionability.COMPLETE
P = Actionability.PARTIAL
Q = Actionability.CLARIFICATION_REQUIRED
B = Actionability.BLOCKED


def _reason(
    code: EvaluationReasonCode,
    effect: Actionability,
    message: str,
    *,
    slot: SemanticSlot | None = None,
    evidence: list[str] | None = None,
    related_ids: list[UUID] | None = None,
) -> EvaluationReason:
    return EvaluationReason(
        code=code,
        effect=effect,
        slot=slot,
        message=message,
        evidence=evidence or [],
        related_ids=related_ids or [],
    )


class InputEvaluator:
    """Deterministic semantic completeness/coherence evaluator."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def evaluate(
        self,
        state: SemanticState,
        *,
        transcript: Transcript | None = None,
        audio: AudioMetadata | None = None,
    ) -> InputEvaluation:
        reasons: list[EvaluationReason] = []

        reasons += self._audio(audio)
        reasons += self._intent(state, transcript)

        if state.intent is not IntentType.UNKNOWN:
            reasons += self._required_slots(state)
            reasons += self._confidence(state)
            reasons += self._references(state)

        reasons += self._ambiguities(state)
        reasons += self._informational(state)

        if not any(reason.effect is not C for reason in reasons):
            reasons.append(
                _reason(
                    EvaluationReasonCode.REQUIRED_SLOTS_PRESENT,
                    C,
                    f"All slots required for {state.intent.value} are stated and coherent.",
                    slot=SemanticSlot.INTENT,
                )
            )

        return InputEvaluation(
            evaluation_id=uuid4(),
            semantic_state_id=state.semantic_state_id,
            actionability=most_restrictive([reason.effect for reason in reasons]),
            reasons=reasons,
            evaluator_version=EVALUATOR_VERSION,
            evaluated_at=self._clock(),
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _audio(audio: AudioMetadata | None) -> list[EvaluationReason]:
        if audio is None:
            return []
        if audio.quality_class is AudioQualityLevel.UNUSABLE:
            return [
                _reason(
                    EvaluationReasonCode.UNUSABLE_AUDIO,
                    B,
                    "The recording contains too little usable speech; ask for a new recording.",
                    evidence=[f"speech_ratio={audio.speech_ratio}"],
                )
            ]
        if audio.quality_class in (AudioQualityLevel.POOR, AudioQualityLevel.DEGRADED):
            return [
                _reason(
                    EvaluationReasonCode.DEGRADED_AUDIO,
                    C,
                    f"Audio quality is {audio.quality_class.value}; transcription errors are "
                    "more likely and downstream confirmation is advisable.",
                    evidence=[f"estimated_snr_db={audio.estimated_snr_db}"],
                )
            ]
        return []

    @staticmethod
    def _has_facts(state: SemanticState) -> bool:
        return bool(state.customer or state.items or state.pricing or state.references)

    def _intent(
        self,
        state: SemanticState,
        transcript: Transcript | None,
    ) -> list[EvaluationReason]:
        if transcript is not None and not transcript.text.strip():
            return [
                _reason(
                    EvaluationReasonCode.EMPTY_TRANSCRIPT,
                    B,
                    "The transcript contains no words.",
                )
            ]
        if state.intent is not IntentType.UNKNOWN:
            return []
        if self._has_facts(state):
            evidence = [state.customer.surface_text] if state.customer else []
            evidence += [
                item.product.surface_text for item in state.items if item.product is not None
            ]
            return [
                _reason(
                    EvaluationReasonCode.ACTION_NOT_SPECIFIED,
                    Q,
                    "Business details were stated but no action was requested.",
                    slot=SemanticSlot.ACTION,
                    evidence=evidence,
                )
            ]
        return [
            _reason(
                EvaluationReasonCode.NO_ACTIONABLE_INTENT,
                B,
                "The utterance does not contain an actionable business request.",
                slot=SemanticSlot.INTENT,
            )
        ]

    @staticmethod
    def _has_reference(state: SemanticState, types: frozenset[ReferenceType]) -> bool:
        return any(reference.reference_type in types for reference in state.references)

    @staticmethod
    def _product_referenced(state: SemanticState, item: SemanticItem) -> bool:
        product_refs = [r for r in state.references if r.reference_type is ReferenceType.PRODUCT]
        return any(r.item_id == item.item_id for r in product_refs) or (
            len(state.items) == 1 and bool(product_refs)
        )

    def _required_slots(self, state: SemanticState) -> list[EvaluationReason]:
        reasons: list[EvaluationReason] = []
        intent = state.intent

        has_customer = state.customer is not None or self._has_reference(
            state, frozenset({ReferenceType.CUSTOMER})
        )
        contextual_items = self._has_reference(state, _CONTEXTUAL_ITEM_REFERENCES)
        product_reference = self._has_reference(state, frozenset({ReferenceType.PRODUCT}))
        customer_ambiguous = any(a.slot is SemanticSlot.CUSTOMER for a in state.ambiguities)

        needs_customer = intent in _LINE_ITEM_INTENTS or intent is IntentType.CREATE_INVOICE
        if needs_customer and not has_customer and not customer_ambiguous:
            reasons.append(
                _reason(
                    EvaluationReasonCode.MISSING_CUSTOMER,
                    Q,
                    f"{intent.value} needs to know which customer it is for.",
                    slot=SemanticSlot.CUSTOMER,
                )
            )

        if intent in _LINE_ITEM_INTENTS or intent is IntentType.CREATE_INVOICE:
            if not state.items and not contextual_items and not product_reference:
                reasons.append(
                    _reason(
                        EvaluationReasonCode.MISSING_ITEMS,
                        Q,
                        "No product or quantity was stated.",
                        slot=SemanticSlot.ITEM,
                    )
                )
            for item in state.items:
                reasons += self._item_reasons(state, item)

        if intent in _PRODUCT_INTENTS:
            has_product = any(item.product for item in state.items) or product_reference
            if not has_product:
                reasons.append(
                    _reason(
                        EvaluationReasonCode.MISSING_PRODUCT,
                        Q,
                        f"{intent.value} needs a product.",
                        slot=SemanticSlot.PRODUCT,
                    )
                )

        if intent in _ORDER_TARGET_INTENTS:
            if has_customer or contextual_items:
                reasons.append(
                    _reason(
                        EvaluationReasonCode.TARGET_ORDER_UNRESOLVED,
                        P,
                        "The existing order to modify must be identified by context resolution.",
                        slot=SemanticSlot.ORDER,
                        evidence=[state.customer.surface_text] if state.customer else [],
                    )
                )
            else:
                reasons.append(
                    _reason(
                        EvaluationReasonCode.MISSING_ORDER_TARGET,
                        Q,
                        "It is not clear which order should be changed.",
                        slot=SemanticSlot.ORDER,
                    )
                )

        return reasons

    def _item_reasons(self, state: SemanticState, item: SemanticItem) -> list[EvaluationReason]:
        reasons: list[EvaluationReason] = []
        conflicted = any(item.item_id in a.related_ids for a in state.ambiguities)

        if item.product is None and not self._product_referenced(state, item):
            reasons.append(
                _reason(
                    EvaluationReasonCode.MISSING_PRODUCT,
                    Q,
                    "A quantity was stated without a product.",
                    slot=SemanticSlot.PRODUCT,
                    evidence=[item.quantity.surface_text] if item.quantity else [],
                    related_ids=[item.item_id],
                )
            )
        if item.quantity is None and not conflicted:
            reasons.append(
                _reason(
                    EvaluationReasonCode.MISSING_QUANTITY,
                    Q,
                    "A product was stated without a quantity.",
                    slot=SemanticSlot.QUANTITY,
                    evidence=[item.product.surface_text] if item.product else [],
                    related_ids=[item.item_id],
                )
            )
        if item.quantity is not None and item.quantity.unit is None:
            reasons.append(
                _reason(
                    EvaluationReasonCode.MISSING_UNIT,
                    Q,
                    "A quantity was stated without a unit.",
                    slot=SemanticSlot.UNIT,
                    evidence=[item.quantity.surface_text],
                    related_ids=[item.item_id],
                )
            )
        return reasons

    @staticmethod
    def _confidence(state: SemanticState) -> list[EvaluationReason]:
        checks: list[tuple[SemanticSlot, str, float, list[UUID]]] = []
        checks.append((SemanticSlot.INTENT, state.intent.value, state.intent_confidence.score, []))
        if state.customer is not None:
            checks.append(
                (
                    SemanticSlot.CUSTOMER,
                    state.customer.surface_text,
                    state.customer.confidence.score,
                    [state.customer.entity_id],
                )
            )
        for item in state.items:
            if item.product is not None:
                checks.append(
                    (
                        SemanticSlot.PRODUCT,
                        item.product.surface_text,
                        item.product.confidence.score,
                        [item.item_id],
                    )
                )
            if item.quantity is not None:
                checks.append(
                    (
                        SemanticSlot.QUANTITY,
                        item.quantity.surface_text,
                        item.quantity.confidence.score,
                        [item.item_id],
                    )
                )

        return [
            _reason(
                EvaluationReasonCode.LOW_CONFIDENCE_SLOT,
                Q,
                f"Low extraction confidence ({score:.2f}) for {slot.value.lower()} "
                f"'{surface_text}'.",
                slot=slot,
                evidence=[surface_text],
                related_ids=related,
            )
            for slot, surface_text, score, related in checks
            if score < LOW_CONFIDENCE_THRESHOLD
        ]

    @staticmethod
    def _references(state: SemanticState) -> list[EvaluationReason]:
        return [
            _reason(
                EvaluationReasonCode.CONTEXT_REFERENCE_UNRESOLVED,
                P,
                f"'{reference.surface_text}' refers to existing business context "
                f"({reference.reference_type.value}) that must be resolved downstream.",
                slot=reference.target_slot,
                evidence=[reference.surface_text],
                related_ids=[reference.reference_id],
            )
            for reference in state.references
        ]

    @staticmethod
    def _ambiguities(state: SemanticState) -> list[EvaluationReason]:
        return [
            _reason(
                EvaluationReasonCode.SEMANTIC_AMBIGUITY,
                Q if ambiguity.requires_clarification else C,
                ambiguity.description,
                slot=ambiguity.slot,
                evidence=ambiguity.candidates,
                related_ids=[ambiguity.ambiguity_id, *ambiguity.related_ids],
            )
            for ambiguity in state.ambiguities
        ]

    @staticmethod
    def _informational(state: SemanticState) -> list[EvaluationReason]:
        reasons = [
            _reason(
                EvaluationReasonCode.CORRECTION_APPLIED,
                C,
                f"{correction.field.value.lower()} corrected from "
                f"'{correction.previous_value.normalized}' to "
                f"'{correction.corrected_value.normalized}'.",
                evidence=[correction.source_text],
                related_ids=[correction.correction_id],
            )
            for correction in state.corrections
        ]
        reasons += [
            _reason(
                EvaluationReasonCode.RELATIVE_DATE_NEEDS_CLOCK,
                C,
                f"'{expression.surface_text}' becomes a calendar date only with the run clock "
                "and business timezone (context resolution).",
                slot=SemanticSlot.DATE,
                evidence=[expression.normalized_expression],
                related_ids=[expression.expression_id],
            )
            for expression in state.temporal_expressions
            if expression.resolution_status is TemporalResolutionStatus.UNRESOLVED
            and expression.kind is not TemporalKind.EXPLICIT_DATE
        ]
        return reasons
