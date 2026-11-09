"""
Records that let the next turn continue a run safely (P2-C, P2-J).

A confirmation asks "I understood X; proceed?" and is bound to one run, the
exact warnings it asks about and the business snapshot it was shown with.
A clarification preserves what was understood and what is missing so the
operator or the next turn does not have to reconstruct the request.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema
from vaaniflow.domain.schemas.understand import UnderstandResult


class ConfirmationStatus(StrEnum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    # Business facts changed after the confirmation was asked; it no longer applies.
    EXPIRED = "EXPIRED"
    # A newer instruction on the same run replaced it.
    SUPERSEDED = "SUPERSEDED"


class PendingConfirmation(DomainSchema):
    confirmation_id: UUID
    run_id: UUID
    status: ConfirmationStatus
    # Deterministic keys of the validation warnings the user is asked to accept.
    warning_keys: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    prompt: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    understand_result: UnderstandResult
    created_at: datetime
    resolved_at: datetime | None = None
    reply_text: str | None = None
    confirmed_by: UUID | None = None
    resolution_reason: str | None = None
    superseded_by: UUID | None = None


class ClarificationStatus(StrEnum):
    OPEN = "OPEN"
    # A newer instruction on the same run replaced the clarified request.
    SUPERSEDED = "SUPERSEDED"


class ClarificationRecord(DomainSchema):
    """
    What was understood, and what is missing, when the system stopped to ask.

    Nothing here is a business fact the system invented: unresolved items
    come from Input Evaluation reasons, semantic ambiguities and failed or
    warning validation checks.
    """

    clarification_id: UUID
    run_id: UUID
    status: ClarificationStatus
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    understood: dict[str, Any] = Field(default_factory=dict)
    understand_result: UnderstandResult
    created_at: datetime
    resolved_at: datetime | None = None
    # Transcript of the newer instruction that replaced this clarification.
    superseded_by_transcript_id: UUID | None = None
