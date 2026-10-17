from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

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
    duration_ms: int | None = Field(default=None, ge=0)

    started_at: datetime
    completed_at: datetime | None = None
