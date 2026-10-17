from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class VerificationStatus(StrEnum):
    PENDING = "PENDING"
    READ_BACK = "READ_BACK"
    COMPARE = "COMPARE"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


class Verification(DomainSchema):
    """
    Independent verification of a tool's claimed business outcome.

    The system must not report a consequential action as successful merely
    because the tool returned a successful acknowledgement.
    """

    verification_id: UUID

    run_id: UUID
    execution_id: UUID

    status: VerificationStatus

    expected_state: dict[str, Any] = Field(default_factory=dict)
    actual_state: dict[str, Any] = Field(default_factory=dict)

    mismatches: list[str] = Field(default_factory=list)

    verified_at: datetime | None = None

    verifier_version: str = Field(min_length=1)