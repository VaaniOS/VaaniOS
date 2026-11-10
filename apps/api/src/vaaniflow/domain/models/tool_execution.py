from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.models.principal import Principal
from vaaniflow.domain.schemas.common import DomainSchema


class ToolSideEffect(StrEnum):
    READ_ONLY = "READ_ONLY"
    DRAFT = "DRAFT"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE_WRITE = "IRREVERSIBLE_WRITE"


class ToolExecutionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ToolExecution(DomainSchema):
    """
    Record of one tool invocation.

    A tool acknowledgement is not equivalent to verified business success.
    Verification is represented separately by the Verification model.
    """

    execution_id: UUID

    run_id: UUID

    tool_name: str = Field(min_length=1)

    side_effect: ToolSideEffect

    status: ToolExecutionStatus

    idempotency_key: str = Field(min_length=1)

    arguments: dict[str, Any] = Field(default_factory=dict)

    result: dict[str, Any] | None = None

    error_code: str | None = None
    error_message: str | None = None

    attempt: int = Field(default=1, ge=1)

    # Audit history of an earlier UNKNOWN outcome for this same execution. The
    # status above always reflects the evidenced business outcome; these fields
    # keep the record of the uncertainty that preceded it.
    reconciled: bool = False  # resolved by read-back of business state, not re-invoked
    prior_status: ToolExecutionStatus | None = None
    prior_error_code: str | None = None
    prior_error_message: str | None = None
    # How an UNKNOWN outcome was settled: RECONCILED_BY_READ_BACK (automatic),
    # OPERATOR_CONFIRMED_SUCCESS / OPERATOR_CONFIRMED_FAILURE (operator, P2-D).
    resolution: str | None = None
    resolved_by: UUID | None = None
    # The authenticated operator who settled it (ADR-022); None for read-back.
    resolved_actor: Principal | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)

    started_at: datetime
    completed_at: datetime | None = None
