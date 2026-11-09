from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from vaaniflow.domain.models.order import Order, OrderItem, OrderStatus
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.domain.policies.decision import (
    Decision,
    DecisionReasonCode,
    DecisionType,
)
from vaaniflow.execution.service import ExecutionService
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    PROD_ULTRATECH_CEMENT_ID,
    WH_PEENYA_ID,
    SyntheticRepositories,
)

_NOW = datetime.now(UTC)


def _make_execute_decision(requires_approval: bool = False) -> Decision:
    return Decision(
        decision_id=uuid4(),
        run_id=uuid4(),
        decision=DecisionType.EXECUTE,
        reason_code=DecisionReasonCode.VALIDATED_LOW_RISK,
        reason="Action fully validated.",
        allowed=True,
        requires_approval=requires_approval,
        policy_version="1.0",
    )


def test_execution_success_with_read_back_verification() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()
    owner_id = uuid4()
    snapshot_v1 = "snap-v1"

    approval = Approval(
        approval_id=uuid4(),
        requested_by=owner_id,
        approved_by=owner_id,
        status=ApprovalStatus.APPROVED,
        snapshot_version=snapshot_v1,
        requested_at=_NOW,
        resolved_at=_NOW,
    )
    repos.approvals.save(approval=approval)

    outcome = service.execute(
        run_id=run_id,
        tool_name="create_order",
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
        idempotency_key="run-1:order-create",
        decision=_make_execute_decision(requires_approval=True),
        approval=approval,
        current_snapshot_version=snapshot_v1,
        expected_state={
            "status": "DRAFT",
            "subtotal": "84000",
            "items_count": 1,
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
        },
        now=_NOW,
    )

    assert outcome.success is True
    assert outcome.execution.status == ToolExecutionStatus.SUCCEEDED
    assert outcome.verification is not None
    assert outcome.verification.status == VerificationStatus.VERIFIED
    assert len(outcome.verification.mismatches) == 0


def test_execution_fails_verification_when_mismatched() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()
    snapshot_v1 = "snap-v1"

    approval = Approval(
        approval_id=uuid4(),
        requested_by=uuid4(),
        approved_by=uuid4(),
        status=ApprovalStatus.APPROVED,
        snapshot_version=snapshot_v1,
        requested_at=_NOW,
        resolved_at=_NOW,
    )

    outcome = service.execute(
        run_id=run_id,
        tool_name="create_order",
        arguments={
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
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
        idempotency_key="run-2:order-create-mismatch",
        decision=_make_execute_decision(requires_approval=True),
        approval=approval,
        current_snapshot_version=snapshot_v1,
        expected_state={
            "subtotal": "99999",  # Deliberate mismatch (actual is 84000)
        },
        now=_NOW,
    )

    # Must NOT claim success if verification fails
    assert outcome.success is False
    assert outcome.execution.status in {ToolExecutionStatus.UNKNOWN, ToolExecutionStatus.FAILED}
    assert outcome.verification is not None
    assert outcome.verification.status == VerificationStatus.MISMATCH
    assert "failed verification" in outcome.message.lower()


def test_policy_blocks_unauthorized_action() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()

    blocked_decision = Decision(
        decision_id=uuid4(),
        run_id=run_id,
        decision=DecisionType.BLOCKED,
        reason_code=DecisionReasonCode.POLICY_VIOLATION,
        reason="Customer identity is ambiguous (2 matches).",
        allowed=False,
        policy_version="1.0",
    )

    outcome = service.execute(
        run_id=run_id,
        tool_name="dispatch_order",
        arguments={"order_id": str(uuid4())},
        idempotency_key="run-3:blocked",
        decision=blocked_decision,
        now=_NOW,
    )

    assert outcome.success is False
    assert outcome.execution.status == ToolExecutionStatus.FAILED
    assert outcome.execution.error_code == "POLICY_BLOCKED"
    assert "ambiguous" in outcome.message.lower()


def test_approval_required_blocks_unapproved_action() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()

    decision = Decision(
        decision_id=uuid4(),
        run_id=run_id,
        decision=DecisionType.EXECUTE,
        reason_code=DecisionReasonCode.APPROVAL_REQUIRED,
        reason="Consequential write requires approval.",
        allowed=True,
        requires_approval=True,
        policy_version="1.0",
    )

    # No approval provided
    outcome = service.execute(
        run_id=run_id,
        tool_name="dispatch_order",
        arguments={"order_id": str(uuid4())},
        idempotency_key="run-4:unapproved",
        decision=decision,
        approval=None,
        now=_NOW,
    )

    assert outcome.success is False
    assert outcome.execution.error_code == "APPROVAL_REQUIRED"
    assert "approval is required" in outcome.message.lower()


def test_approval_expired_blocks_action_scenario_h() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()

    approval = Approval(
        approval_id=uuid4(),
        requested_by=uuid4(),
        approved_by=uuid4(),
        status=ApprovalStatus.APPROVED,
        snapshot_version="v1-quote-old",
        requested_at=_NOW,
        resolved_at=_NOW,
    )

    outcome = service.execute(
        run_id=run_id,
        tool_name="dispatch_order",
        arguments={
            "order_id": str(uuid4()),
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "warehouse_id": str(WH_PEENYA_ID),
        },
        idempotency_key="run-5:expired-snapshot",
        decision=_make_execute_decision(requires_approval=True),
        approval=approval,
        current_snapshot_version="v2-quote-renegotiated",  # Snapshot changed!
        now=_NOW,
    )

    assert outcome.success is False
    assert outcome.execution.error_code == "APPROVAL_EXPIRED"
    assert "re-approval required" in outcome.message.lower()


def test_invoice_failure_preserves_draft_scenario_f() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()
    invoice_id = uuid4()

    # Seed draft invoice
    invoice = Invoice(
        invoice_id=invoice_id,
        order_id=uuid4(),
        customer_id=CUST_SHARMA_BUILDERS_ID,
        items=[
            InvoiceItem(
                item_id=uuid4(),
                product_id=PROD_ULTRATECH_CEMENT_ID,
                quantity=200,
                unit="bags",
                unit_price=Decimal(420),
                line_total=Decimal(84000),
            )
        ],
        currency="INR",
        subtotal=Decimal(84000),
        tax_total=Decimal(23520),
        total=Decimal(107520),
        status=InvoiceStatus.DRAFT,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.invoices.save(invoice=invoice)

    approval = Approval(
        approval_id=uuid4(),
        requested_by=uuid4(),
        approved_by=uuid4(),
        status=ApprovalStatus.APPROVED,
        snapshot_version="v1",
        requested_at=_NOW,
        resolved_at=_NOW,
    )

    # Execute issue_invoice with failure simulation
    outcome = service.execute(
        run_id=run_id,
        tool_name="issue_invoice",
        arguments={"invoice_id": str(invoice_id)},
        idempotency_key="run-6:fail-invoice",
        decision=_make_execute_decision(requires_approval=True),
        approval=approval,
        current_snapshot_version="v1",
        metadata={"simulate_invoice_failure": True},
        now=_NOW,
    )

    # Invariant: Never fake success!
    assert outcome.success is False
    assert outcome.execution.status == ToolExecutionStatus.FAILED
    assert outcome.execution.error_code == "INVOICE_GATEWAY_TIMEOUT"
    assert (
        "draft preserved" in outcome.message.lower()
        or "kept the validated draft" in outcome.message.lower()
    )

    # Draft remains intact in repository
    persisted_inv = repos.invoices.get_by_id(invoice_id=invoice_id)
    assert persisted_inv is not None
    assert persisted_inv.status == InvoiceStatus.DRAFT


def test_dispatch_failure_never_fakes_success_scenario_g() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()

    approval = Approval(
        approval_id=uuid4(),
        requested_by=uuid4(),
        approved_by=uuid4(),
        status=ApprovalStatus.APPROVED,
        snapshot_version="v1",
        requested_at=_NOW,
        resolved_at=_NOW,
    )

    outcome = service.execute(
        run_id=run_id,
        tool_name="dispatch_order",
        arguments={
            "order_id": str(uuid4()),
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "warehouse_id": str(WH_PEENYA_ID),
        },
        idempotency_key="run-7:fail-dispatch",
        decision=_make_execute_decision(requires_approval=True),
        approval=approval,
        current_snapshot_version="v1",
        metadata={"simulate_dispatch_failure": True},
        now=_NOW,
    )

    # Invariant: Never fake success on dispatch failure!
    assert outcome.success is False
    assert outcome.execution.status == ToolExecutionStatus.FAILED
    assert "could not be executed" in outcome.message.lower()


def test_idempotency_prevents_duplicate_tool_execution() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    run_id = uuid4()
    order_id = uuid4()

    # Seed an order to read
    order = Order(
        order_id=order_id,
        customer_id=CUST_SHARMA_BUILDERS_ID,
        items=[
            OrderItem(
                item_id=uuid4(),
                product_id=PROD_ULTRATECH_CEMENT_ID,
                quantity=10,
                unit="bags",
                unit_price=Decimal(420),
                line_total=Decimal(4200),
            )
        ],
        currency="INR",
        subtotal=Decimal(4200),
        status=OrderStatus.CONFIRMED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.orders.save(order=order)

    idempotency_key = "idemp-key-unique-read"

    # First call
    out1 = service.execute(
        run_id=run_id,
        tool_name="read_order",
        arguments={"order_id": str(order_id)},
        idempotency_key=idempotency_key,
        decision=_make_execute_decision(requires_approval=False),
        now=_NOW,
    )
    assert out1.success is True

    # Second call with same idempotency key
    out2 = service.execute(
        run_id=run_id,
        tool_name="read_order",
        arguments={"order_id": str(order_id)},
        idempotency_key=idempotency_key,
        decision=_make_execute_decision(requires_approval=False),
        now=_NOW,
    )
    assert out2.success is True
    assert "idempotency match" in out2.message.lower()
    assert out2.execution.execution_id == out1.execution.execution_id
