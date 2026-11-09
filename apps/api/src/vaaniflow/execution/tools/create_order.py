from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.order import Order, OrderItem, OrderStatus
from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult


class CreateOrderTool(Tool):
    """Creates a business order from validated line items."""

    name = "create_order"
    purpose = "Create a draft order in the business system"
    side_effect = ToolSideEffect.REVERSIBLE_WRITE
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            customer_id = UUID(str(arguments["customer_id"]))
            currency = str(arguments.get("currency", "INR"))
            recipient_name = arguments.get("recipient_name")
            delivery_address = arguments.get("delivery_address")

            raw_items = arguments.get("items", [])
            order_items: list[OrderItem] = []
            subtotal = Decimal(0)

            for item in raw_items:
                p_id = UUID(str(item["product_id"]))
                qty = int(item["quantity"])
                unit = str(item["unit"])
                u_price = Decimal(str(item["unit_price"]))
                line_total = Decimal(str(item.get("line_total", u_price * qty)))

                order_items.append(
                    OrderItem(
                        item_id=uuid4(),
                        product_id=p_id,
                        quantity=qty,
                        unit=unit,
                        unit_price=u_price,
                        line_total=line_total,
                    )
                )
                subtotal += line_total

            order = Order(
                order_id=uuid4(),
                customer_id=customer_id,
                recipient_name=recipient_name,
                delivery_address=delivery_address,
                items=order_items,
                currency=currency,
                subtotal=subtotal,
                status=OrderStatus.DRAFT,
                source_run_id=context.run_id,
                created_at=context.now,
                updated_at=context.now,
            )

            context.repositories.orders.save(order=order)

            return ToolResult(
                success=True,
                data={
                    "order_id": str(order.order_id),
                    "customer_id": str(order.customer_id),
                    "subtotal": str(order.subtotal),
                    "currency": order.currency,
                    "items_count": len(order.items),
                    "status": order.status.value,
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="ORDER_CREATION_FAILED",
                error_message=str(e),
            )
