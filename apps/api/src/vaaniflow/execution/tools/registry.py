from vaaniflow.execution.tools.base import Tool
from vaaniflow.execution.tools.create_invoice_draft import CreateInvoiceDraftTool
from vaaniflow.execution.tools.create_order import CreateOrderTool
from vaaniflow.execution.tools.dispatch_order import DispatchOrderTool
from vaaniflow.execution.tools.issue_invoice import IssueInvoiceTool
from vaaniflow.execution.tools.read_tools import (
    ReadDispatchTool,
    ReadInvoiceTool,
    ReadOrderTool,
)


class ToolRegistry:
    """Registry for discovering, inspecting, and retrieving available business tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance by its declared name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())


def create_default_registry() -> ToolRegistry:
    """Instantiate and populate the standard registry of SME business tools."""
    registry = ToolRegistry()
    registry.register(CreateOrderTool())
    registry.register(CreateInvoiceDraftTool())
    registry.register(IssueInvoiceTool())
    registry.register(DispatchOrderTool())
    registry.register(ReadOrderTool())
    registry.register(ReadInvoiceTool())
    registry.register(ReadDispatchTool())
    return registry
