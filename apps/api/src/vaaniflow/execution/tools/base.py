from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


@dataclass
class ToolContext:
    """Runtime context passed to a tool during execution."""

    run_id: UUID
    repositories: SyntheticRepositories
    idempotency_key: str
    now: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Standardized outcome of executing a tool."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    # True when the tool cannot tell whether the write was committed (e.g. a
    # timeout after the request was sent). Never treated as a definite failure.
    outcome_unknown: bool = False


TIMEOUT_BEFORE_COMMIT = "before_commit"
TIMEOUT_AFTER_COMMIT = "after_commit"


def simulated_timeout(context: ToolContext, tool_name: str) -> str | None:
    """
    Sandbox fault: the call times out ``before_commit`` (nothing written) or
    ``after_commit`` (written, but the response is lost). Either way the
    caller cannot tell which happened.
    """
    faults = context.metadata.get("simulate_timeout")
    if isinstance(faults, dict):
        mode = faults.get(tool_name)
        if mode in {TIMEOUT_BEFORE_COMMIT, TIMEOUT_AFTER_COMMIT}:
            return str(mode)
    return None


def timeout_result(tool_name: str) -> ToolResult:
    """An uncertain outcome: the write may or may not have been committed."""
    return ToolResult(
        success=False,
        outcome_unknown=True,
        error_code="TOOL_TIMEOUT",
        error_message=(
            f"No response from the business system for {tool_name}; "
            "the write may or may not have been committed."
        ),
    )


class Tool(ABC):
    """
    Abstract base class for all agentic and business tools.

    Declares name, description, side-effect level, and idempotency property.
    """

    name: str
    purpose: str
    side_effect: ToolSideEffect
    is_idempotent: bool

    @abstractmethod
    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool with given arguments and runtime context."""
        ...
