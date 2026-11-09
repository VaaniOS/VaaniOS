from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from vaaniflow.domain.models.order import OrderStatus
from vaaniflow.domain.models.tool_execution import ToolSideEffect
from vaaniflow.execution.tools.base import ToolContext
from vaaniflow.execution.tools.create_invoice_draft import CreateInvoiceDraftTool
from vaaniflow.execution.tools.create_order import CreateOrderTool
from vaaniflow.execution.tools.dispatch_order import DispatchOrderTool
from vaaniflow.execution.tools.issue_invoice import IssueInvoiceTool
from vaaniflow.execution.tools.read_tools import (
    ReadDispatchTool,
    ReadInvoiceTool,
    ReadOrderTool,
)
from vaaniflow.execution.tools.registry import create_default_registry
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    PROD_ULTRATECH_CEMENT_ID,
    WH_PEENYA_ID,
    SyntheticRepositories,
)


def _make_context(repos: SyntheticRepositories, metadata: dict | None = None) -> ToolContext:
    return ToolContext(
        run_id=uuid4(),
        repositories=repos,
        idempotency_key=str(uuid4()),
        now=datetime.now(UTC),
        metadata=metadata or {},
    )


def test_create_order_tool_success() -> None:
    repos = SyntheticRepositories()
    ctx = _make_context(repos)
    tool = CreateOrderTool()

    assert tool.side_effect == ToolSideEffect.REVERSIBLE_WRITE
    assert tool.is_idempotent is True

    result = tool.execute(
        arguments={
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "recipient_name": "Sharma Site Manager",
            "delivery_address": "Site 12, Peenya",
            "items": [
                {
                    "product_id": str(PROD_ULTRATECH_CEMENT_ID),
                    "quantity": 200,
                    "unit": "bags",
                    "unit_price": "420",
                    "line_total": "84000",
                }
            ],
        },
        context=ctx,
    )

    assert result.success is True
    order_id = UUID(result.data["order_id"])
    saved_order = repos.orders.get_by_id(order_id=order_id)
    assert saved_order is not None
    assert saved_order.subtotal == Decimal(84000)
    assert saved_order.status == OrderStatus.DRAFT


def test_create_invoice_draft_and_issue_success() -> None:
    repos = SyntheticRepositories()
    ctx = _make_context(repos)
    order_id = uuid4()

    draft_tool = CreateInvoiceDraftTool()
    assert draft_tool.side_effect == ToolSideEffect.DRAFT

    draft_result = draft_tool.execute(
        arguments={
            "order_id": str(order_id),
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "subtotal": "84000",
            "tax_total": "23520",
            "total": "107520",
            "items": [
                {
                    "product_id": str(PROD_ULTRATECH_CEMENT_ID),
                    "quantity": 200,
                    "unit": "bags",
                    "unit_price": "420",
                    "line_total": "84000",
                }
            ],
        },
        context=ctx,
    )

    assert draft_result.success is True
    invoice_id = UUID(draft_result.data["invoice_id"])
    assert draft_result.data["status"] == "DRAFT"

    # Now issue the invoice
    issue_tool = IssueInvoiceTool()
    issue_result = issue_tool.execute(
        arguments={"invoice_id": str(invoice_id)},
        context=ctx,
    )

    assert issue_result.success is True
    assert issue_result.data["status"] == "ISSUED"

    saved_invoice = repos.invoices.get_by_id(invoice_id=invoice_id)
    assert saved_invoice is not None
    assert saved_invoice.status.value == "ISSUED"


def test_issue_invoice_tool_simulated_failure_scenario_f() -> None:
    repos = SyntheticRepositories()
    # Provide sandbox failure toggle
    ctx = _make_context(repos, metadata={"simulate_invoice_failure": True})
    invoice_id = uuid4()

    tool = IssueInvoiceTool()
    result = tool.execute(
        arguments={"invoice_id": str(invoice_id)},
        context=ctx,
    )

    assert result.success is False
    assert result.error_code == "INVOICE_GATEWAY_TIMEOUT"
    assert "draft preserved" in result.error_message.lower()


def test_dispatch_order_tool_success_and_simulated_failure_scenario_g() -> None:
    repos = SyntheticRepositories()
    ctx = _make_context(repos)
    order_id = uuid4()

    tool = DispatchOrderTool()
    assert tool.side_effect == ToolSideEffect.IRREVERSIBLE_WRITE

    # Happy path
    result = tool.execute(
        arguments={
            "order_id": str(order_id),
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "warehouse_id": str(WH_PEENYA_ID),
            "delivery_address": "Site 12, Outer Ring Road",
            "recipient_name": "Ramesh Site Incharge",
        },
        context=ctx,
    )
    assert result.success is True
    dispatch_id = UUID(result.data["dispatch_id"])
    saved_dispatch = repos.dispatches.get_by_id(dispatch_id=dispatch_id)
    assert saved_dispatch is not None
    assert saved_dispatch.status.value == "DISPATCHED"

    # Simulated failure (Scenario G)
    fail_ctx = _make_context(repos, metadata={"simulate_dispatch_failure": True})
    fail_result = tool.execute(
        arguments={
            "order_id": str(order_id),
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "warehouse_id": str(WH_PEENYA_ID),
        },
        context=fail_ctx,
    )
    assert fail_result.success is False
    assert fail_result.error_code == "DISPATCH_API_ERROR"


def test_read_tools_success_and_not_found() -> None:
    repos = SyntheticRepositories()
    ctx = _make_context(repos)

    read_order = ReadOrderTool()
    read_invoice = ReadInvoiceTool()
    read_dispatch = ReadDispatchTool()

    assert read_order.side_effect == ToolSideEffect.READ_ONLY
    assert read_invoice.side_effect == ToolSideEffect.READ_ONLY
    assert read_dispatch.side_effect == ToolSideEffect.READ_ONLY

    # Non-existent
    missing_id = uuid4()
    assert read_order.execute(arguments={"order_id": str(missing_id)}, context=ctx).success is False
    assert (
        read_invoice.execute(arguments={"invoice_id": str(missing_id)}, context=ctx).success
        is False
    )
    assert (
        read_dispatch.execute(arguments={"dispatch_id": str(missing_id)}, context=ctx).success
        is False
    )

    # Create and read back
    order_tool = CreateOrderTool()
    o_res = order_tool.execute(
        arguments={
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "items": [
                {
                    "product_id": str(PROD_ULTRATECH_CEMENT_ID),
                    "quantity": 10,
                    "unit": "bags",
                    "unit_price": "420",
                    "line_total": "4200",
                }
            ],
        },
        context=ctx,
    )
    assert o_res.success is True
    o_id = o_res.data["order_id"]
    r_res = read_order.execute(arguments={"order_id": o_id}, context=ctx)
    assert r_res.success is True
    assert r_res.data["order_id"] == o_id


def test_tool_registry() -> None:
    registry = create_default_registry()
    assert registry.has("create_order")
    assert registry.has("create_invoice_draft")
    assert registry.has("issue_invoice")
    assert registry.has("dispatch_order")
    assert registry.has("read_order")
    assert registry.has("read_invoice")
    assert registry.has("read_dispatch")
    assert not registry.has("non_existent_tool")
    assert len(registry.list_tools()) == 7
