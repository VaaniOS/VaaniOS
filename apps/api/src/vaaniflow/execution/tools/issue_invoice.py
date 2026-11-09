from typing import Any
from uuid import UUID

from vaaniflow.domain.models.invoice import InvoiceStatus
from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult


class IssueInvoiceTool(Tool):
    """Finalizes and issues an invoice after required owner approval."""

    name = "issue_invoice"
    purpose = "Formally issue an approved invoice"
    side_effect = ToolSideEffect.REVERSIBLE_WRITE
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        # Failure injection sandbox support (Scenario F)
        if context.metadata.get("simulate_invoice_failure"):
            return ToolResult(
                success=False,
                error_code="INVOICE_GATEWAY_TIMEOUT",
                error_message="External billing service unavailable. Validated draft preserved.",
            )

        try:
            invoice_id = UUID(str(arguments["invoice_id"]))
            invoice = context.repositories.invoices.get_by_id(invoice_id=invoice_id)
            if invoice is None:
                return ToolResult(
                    success=False,
                    error_code="INVOICE_NOT_FOUND",
                    error_message=f"Invoice {invoice_id} not found in repository.",
                )

            # Transition to ISSUED
            invoice.status = InvoiceStatus.ISSUED
            invoice.updated_at = context.now
            context.repositories.invoices.save(invoice=invoice)

            return ToolResult(
                success=True,
                data={
                    "invoice_id": str(invoice.invoice_id),
                    "status": invoice.status.value,
                    "total": str(invoice.total),
                    "issued_at": context.now.isoformat(),
                },
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(
                success=False,
                error_code="INVOICE_ISSUANCE_FAILED",
                error_message=str(e),
            )
