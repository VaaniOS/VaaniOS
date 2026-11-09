from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import (
    TIMEOUT_AFTER_COMMIT,
    TIMEOUT_BEFORE_COMMIT,
    Tool,
    ToolContext,
    ToolResult,
    simulated_timeout,
    timeout_result,
)


class CreateInvoiceDraftTool(Tool):
    """Creates a draft invoice for owner review and preview."""

    name = "create_invoice_draft"
    purpose = "Generate an invoice preview draft with line items and taxes"
    side_effect = ToolSideEffect.DRAFT
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        timeout = simulated_timeout(context, self.name)
        if timeout == TIMEOUT_BEFORE_COMMIT:
            return timeout_result(self.name)
        # Failure injection sandbox support (Scenario F)
        if context.metadata.get("simulate_invoice_failure"):
            return ToolResult(
                success=False,
                error_code="INVOICE_GATEWAY_TIMEOUT",
                error_message="External billing service unavailable. No invoice was created.",
            )
        try:
            order_id = UUID(str(arguments["order_id"]))
            customer_id = UUID(str(arguments["customer_id"]))
            currency = str(arguments.get("currency", "INR"))
            subtotal = Decimal(str(arguments["subtotal"]))
            tax_total = Decimal(str(arguments["tax_total"]))
            total = Decimal(str(arguments["total"]))

            raw_items = arguments.get("items", [])
            invoice_items: list[InvoiceItem] = []

            for item in raw_items:
                p_id = UUID(str(item["product_id"]))
                qty = int(item["quantity"])
                unit = str(item["unit"])
                u_price = Decimal(str(item["unit_price"]))
                line_total = Decimal(str(item.get("line_total", u_price * qty)))

                invoice_items.append(
                    InvoiceItem(
                        item_id=uuid4(),
                        product_id=p_id,
                        quantity=qty,
                        unit=unit,
                        unit_price=u_price,
                        line_total=line_total,
                    )
                )

            invoice = Invoice(
                invoice_id=uuid4(),
                order_id=order_id,
                customer_id=customer_id,
                items=invoice_items,
                currency=currency,
                subtotal=subtotal,
                tax_total=tax_total,
                total=total,
                status=InvoiceStatus.DRAFT,
                idempotency_key=context.idempotency_key,
                created_at=context.now,
                updated_at=context.now,
            )

            context.repositories.invoices.save(invoice=invoice)
            if timeout == TIMEOUT_AFTER_COMMIT:
                return timeout_result(self.name)

            return ToolResult(
                success=True,
                data={
                    "invoice_id": str(invoice.invoice_id),
                    "order_id": str(invoice.order_id),
                    "customer_id": str(invoice.customer_id),
                    "subtotal": str(invoice.subtotal),
                    "tax_total": str(invoice.tax_total),
                    "total": str(invoice.total),
                    "status": invoice.status.value,
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="INVOICE_DRAFT_FAILED",
                error_message=str(e),
            )
