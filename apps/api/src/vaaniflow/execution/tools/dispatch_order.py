from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.dispatch import Dispatch, DispatchStatus
from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult


class DispatchOrderTool(Tool):
    """Executes physical order dispatch with warehouse."""

    name = "dispatch_order"
    purpose = "Instruct the warehouse to dispatch goods to customer"
    side_effect = ToolSideEffect.IRREVERSIBLE_WRITE
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        # Failure injection sandbox support (Scenario G)
        if context.metadata.get("simulate_dispatch_failure"):
            return ToolResult(
                success=False,
                error_code="DISPATCH_API_ERROR",
                error_message="Warehouse transport gateway rejected dispatch: vehicle unavailable.",
            )

        try:
            order_id = UUID(str(arguments["order_id"]))
            customer_id = UUID(str(arguments["customer_id"]))
            warehouse_id = UUID(str(arguments["warehouse_id"]))
            delivery_address = arguments.get("delivery_address")
            recipient_name = arguments.get("recipient_name")

            dispatch = Dispatch(
                dispatch_id=uuid4(),
                order_id=order_id,
                customer_id=customer_id,
                warehouse_id=warehouse_id,
                status=DispatchStatus.DISPATCHED,
                recipient_name=recipient_name,
                delivery_address=delivery_address,
                created_at=context.now,
                updated_at=context.now,
            )

            context.repositories.dispatches.save(dispatch=dispatch)

            return ToolResult(
                success=True,
                data={
                    "dispatch_id": str(dispatch.dispatch_id),
                    "order_id": str(dispatch.order_id),
                    "warehouse_id": str(dispatch.warehouse_id),
                    "status": dispatch.status.value,
                    "dispatched_at": context.now.isoformat(),
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="DISPATCH_FAILED",
                error_message=str(e),
            )
