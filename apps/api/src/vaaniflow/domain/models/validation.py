from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class ValidationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ValidationStatus(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class ValidationCheck(DomainSchema):
    """One deterministic validation check performed on a proposed action."""

    check_id: UUID

    check_type: str = Field(min_length=1)
    status: ValidationStatus
    severity: ValidationSeverity

    message: str = Field(min_length=1)

    field: str | None = None

    expected: Any | None = None
    actual: Any | None = None

    evidence: list[str] = Field(default_factory=list)


class ValidationResult(DomainSchema):
    """
    Aggregate result of deterministic validation before execution.

    Validation answers:
        "Is the proposed business state valid?"

    It does not decide whether the action is allowed or whether it is
    sufficiently safe to execute. Those concerns belong to policy and risk.
    """

    validation_id: UUID

    run_id: UUID

    status: ValidationStatus

    checks: list[ValidationCheck] = Field(default_factory=list)

    validated_at: datetime

    validator_version: str = Field(min_length=1)