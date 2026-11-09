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
