from typing import Any
from uuid import UUID

from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult


class ReadOrderTool(Tool):
    """Retrieves an existing order record from the repository."""

    name = "read_order"
    purpose = "Read order state from the business repository"
    side_effect = ToolSideEffect.READ_ONLY
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            order_id = UUID(str(arguments["order_id"]))
            order = context.repositories.orders.get_by_id(order_id=order_id)
            if order is None:
                return ToolResult(
                    success=False,
                    error_code="ORDER_NOT_FOUND",
                    error_message=f"Order {order_id} not found in repository.",
                )

            return ToolResult(
                success=True,
                data={
                    "order_id": str(order.order_id),
                    "customer_id": str(order.customer_id),
                    "recipient_name": order.recipient_name,
                    "delivery_address": order.delivery_address,
                    "subtotal": str(order.subtotal),
                    "currency": order.currency,
                    "items_count": len(order.items),
                    "status": order.status.value,
                    "created_at": order.created_at.isoformat(),
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="READ_ORDER_FAILED",
                error_message=str(e),
            )


class ReadInvoiceTool(Tool):
    """Retrieves an existing invoice record from the repository."""

    name = "read_invoice"
    purpose = "Read invoice state from the business repository"
    side_effect = ToolSideEffect.READ_ONLY
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            invoice_id = UUID(str(arguments["invoice_id"]))
            invoice = context.repositories.invoices.get_by_id(invoice_id=invoice_id)
            if invoice is None:
                return ToolResult(
                    success=False,
                    error_code="INVOICE_NOT_FOUND",
                    error_message=f"Invoice {invoice_id} not found in repository.",
                )

            return ToolResult(
                success=True,
                data={
                    "invoice_id": str(invoice.invoice_id),
                    "order_id": str(invoice.order_id),
                    "customer_id": str(invoice.customer_id),
                    "subtotal": str(invoice.subtotal),
                    "tax_total": str(invoice.tax_total),
                    "total": str(invoice.total),
                    "currency": invoice.currency,
                    "items_count": len(invoice.items),
                    "status": invoice.status.value,
                    "created_at": invoice.created_at.isoformat(),
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="READ_INVOICE_FAILED",
                error_message=str(e),
            )


class ReadDispatchTool(Tool):
    """Retrieves an existing dispatch record from the repository."""

    name = "read_dispatch"
    purpose = "Read dispatch state from the business repository"
    side_effect = ToolSideEffect.READ_ONLY
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            dispatch_id = UUID(str(arguments["dispatch_id"]))
            dispatch = context.repositories.dispatches.get_by_id(dispatch_id=dispatch_id)
            if dispatch is None:
                return ToolResult(
                    success=False,
                    error_code="DISPATCH_NOT_FOUND",
                    error_message=f"Dispatch {dispatch_id} not found in repository.",
                )

            return ToolResult(
                success=True,
                data={
                    "dispatch_id": str(dispatch.dispatch_id),
                    "order_id": str(dispatch.order_id),
                    "customer_id": str(dispatch.customer_id),
                    "warehouse_id": str(dispatch.warehouse_id),
                    "recipient_name": dispatch.recipient_name,
                    "delivery_address": dispatch.delivery_address,
                    "status": dispatch.status.value,
                    "created_at": dispatch.created_at.isoformat(),
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="READ_DISPATCH_FAILED",
                error_message=str(e),
            )
