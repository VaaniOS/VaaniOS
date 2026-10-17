"""
UNDERSTAND → ACT handoff contract (ADR-013).

``UnderstandResult`` is the only object the ACT side needs to consume. It
carries what the user said (transcript), what was understood (SemanticState),
whether that understanding is actionable (InputEvaluation) and where the
audio came from (AudioProvenance). It contains no business facts.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import Actionability, DomainSchema
from vaaniflow.domain.schemas.semantic import SemanticSlot, SemanticState
from vaaniflow.domain.schemas.transcript import Transcript

UNDERSTAND_SCHEMA_VERSION = "1.0"

_ACTIONABILITY_ORDER = (
    Actionability.COMPLETE,
    Actionability.PARTIAL,
    Actionability.CLARIFICATION_REQUIRED,
    Actionability.BLOCKED,
)


def most_restrictive(values: list[Actionability]) -> Actionability:
    """Return the most restrictive actionability (BLOCKED > ... > COMPLETE)."""
    return max(values, key=_ACTIONABILITY_ORDER.index, default=Actionability.COMPLETE)


class EvaluationReasonCode(StrEnum):
    # COMPLETE (informational)
    REQUIRED_SLOTS_PRESENT = "REQUIRED_SLOTS_PRESENT"
    CORRECTION_APPLIED = "CORRECTION_APPLIED"
    RELATIVE_DATE_NEEDS_CLOCK = "RELATIVE_DATE_NEEDS_CLOCK"
    DEGRADED_AUDIO = "DEGRADED_AUDIO"

    # PARTIAL
    CONTEXT_REFERENCE_UNRESOLVED = "CONTEXT_REFERENCE_UNRESOLVED"
    TARGET_ORDER_UNRESOLVED = "TARGET_ORDER_UNRESOLVED"

    # CLARIFICATION_REQUIRED
    ACTION_NOT_SPECIFIED = "ACTION_NOT_SPECIFIED"
    MISSING_CUSTOMER = "MISSING_CUSTOMER"
    MISSING_ITEMS = "MISSING_ITEMS"
    MISSING_PRODUCT = "MISSING_PRODUCT"
    MISSING_QUANTITY = "MISSING_QUANTITY"
    MISSING_UNIT = "MISSING_UNIT"
    MISSING_ORDER_TARGET = "MISSING_ORDER_TARGET"
    SEMANTIC_AMBIGUITY = "SEMANTIC_AMBIGUITY"
    LOW_CONFIDENCE_SLOT = "LOW_CONFIDENCE_SLOT"
    NEGATED_ACTION = "NEGATED_ACTION"

    # BLOCKED
    EMPTY_TRANSCRIPT = "EMPTY_TRANSCRIPT"
    NO_ACTIONABLE_INTENT = "NO_ACTIONABLE_INTENT"
    UNUSABLE_AUDIO = "UNUSABLE_AUDIO"


class EvaluationReason(DomainSchema):
    """One piece of evidence behind an actionability classification."""

    code: EvaluationReasonCode
    effect: Actionability
    slot: SemanticSlot | None = None
    message: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    related_ids: list[UUID] = Field(default_factory=list)


class InputEvaluation(DomainSchema):
    """
    Semantic completeness / coherence assessment of a SemanticState.

    COMPLETE: sufficiently specified and internally coherent.
    PARTIAL: understood, but depends on downstream context resolution of
        references (previous rate, same customer, that order, ...).
    CLARIFICATION_REQUIRED: the user must supply or disambiguate information.
    BLOCKED: not an actionable request.

    This is not business validation: it never consults business data.
    """

    evaluation_id: UUID
    semantic_state_id: UUID
    actionability: Actionability
    reasons: list[EvaluationReason] = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    evaluated_at: datetime

    @model_validator(mode="after")
    def _check_actionability(self) -> Self:
        expected = most_restrictive([reason.effect for reason in self.reasons])
        if expected is not self.actionability:
            raise ValueError(
                f"actionability {self.actionability} does not match reasons ({expected})"
            )
        return self


class AudioProvenance(DomainSchema):
    """Lineage of the audio that produced the transcript."""

    original_artifact_id: UUID
    processed_artifact_id: UUID
    processed_metadata: AudioMetadata
    applied_operations: list[str] = Field(default_factory=list)


class UnderstandResult(DomainSchema):
    """The UNDERSTAND side's complete, provider-neutral output."""

    result_id: UUID
    schema_version: Literal["1.0"] = "1.0"
    run_id: UUID | None = None

    transcript: Transcript
    audio: AudioProvenance | None = None
    semantic_state: SemanticState
    evaluation: InputEvaluation

    created_at: datetime

    @property
    def actionability(self) -> Actionability:
        return self.evaluation.actionability

    @model_validator(mode="after")
    def _check_links(self) -> Self:
        if self.semantic_state.source_transcript_id != self.transcript.transcript_id:
            raise ValueError("semantic state was not compiled from this transcript")
        if self.evaluation.semantic_state_id != self.semantic_state.semantic_state_id:
            raise ValueError("evaluation does not belong to this semantic state")
        if self.semantic_state.run_id != self.run_id:
            raise ValueError("semantic state run_id does not match the result run_id")
        return self
