"""
Phase C P2 regressions: business duplicate detection, approval audit metadata,
bound confirmation, operator resolution of UNKNOWN, end-to-end audit linkage,
state-derived status wording, verification contracts, quote semantics,
temporal reference linkage and clarification preservation.

Execution tests assert repository state, not only returned statuses.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from vaaniflow.api.app import app
from vaaniflow.api.dependencies import AppContainer, reset_container
from vaaniflow.application.services.orchestrator import (
    ConfirmationFlowError,
    VoiceWorkflowOrchestrator,
    WorkflowResult,
)
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.dispatch import Dispatch, DispatchStatus
from vaaniflow.domain.models.followup import ClarificationStatus, ConfirmationStatus
from vaaniflow.domain.models.order import Order, OrderItem, OrderStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus, ToolSideEffect
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionReasonCode, DecisionType
from vaaniflow.domain.schemas.semantic import ReferenceType
from vaaniflow.execution import plan as plan_module
from vaaniflow.execution.duplicates import DuplicateStatus
from vaaniflow.execution.plan import (
    UNPLANNABLE_WRITE_TOOLS,
    VERIFICATION_CONTRACTS,
    PlanningError,
    StepStatus,
    build_plan,
    expected_state_for,
)
from vaaniflow.execution.tools.base import ToolContext
from vaaniflow.execution.tools.create_order import CreateOrderTool
from vaaniflow.execution.tools.registry import create_default_registry
from vaaniflow.infrastructure.repositories.memory import InMemoryQuoteRepository
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_KUMAR_CONSTRUCTIONS_ID,
    CUST_SHARMA_BUILDERS_ID,
    PROD_ACC_CEMENT_ID,
    PROD_ULTRATECH_CEMENT_ID,
    QUOTE_KUMAR_ACC_VALID_ID,
    QUOTE_SHARMA_ULTRATECH_VALID_ID,
    SYNTHETIC_BUSINESS_TIME,
    WH_PEENYA_ID,
    SyntheticRepositories,
    get_synthetic_quotes,
)

T = SYNTHETIC_BUSINESS_TIME  # 2026-10-17 12:00 IST; "parso" = 2026-10-15
D = date(2026, 10, 15)

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)
KUMAR = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
KUMAR_11 = "Kumar Constructions ko 11 bags ACC cement ₹400 per bag dispatch karo."
KUMAR_RUPEE = "Kumar Constructions ko 10 bags ACC cement ₹1 per bag dispatch karo."
SHARMA_UT = "Sharma Builders ko 10 bags UltraTech cement ₹420 per bag dispatch karo."
SHARMA_ACC = "Sharma Builders ko 10 bags ACC cement ₹400 per bag dispatch karo."
SHARMA_ORDER_ONLY = "Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka order banao."
SHARMA_INVOICE_DISPATCH = (
    "Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka invoice banao aur dispatch karo."
)

client = TestClient(app)


def _setup() -> tuple[SyntheticRepositories, VoiceWorkflowOrchestrator]:
    repos = SyntheticRepositories()
    return repos, VoiceWorkflowOrchestrator(repositories=repos, clock=lambda: T)


def _writes(repos: SyntheticRepositories) -> tuple[int, int, int]:
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


def _approve(
    orchestrator: VoiceWorkflowOrchestrator,
    result: WorkflowResult,
    *,
    faults: dict[str, Any] | None = None,
    approved_by: UUID | None = None,
) -> WorkflowResult:
    assert result.approval is not None
    return orchestrator.approve(
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        approved_by=approved_by,
        simulated_faults=faults,
    )


def _seed_order(
    repos: SyntheticRepositories,
    *,
    customer_id: UUID = CUST_KUMAR_CONSTRUCTIONS_ID,
    product_id: UUID = PROD_ACC_CEMENT_ID,
    quantity: int = 10,
    unit_price: str = "400.00",
    address: str | None = None,
    status: OrderStatus = OrderStatus.DRAFT,
    created_at: datetime = T,
    dispatched: bool = False,
) -> Order:
    customer = repos.customers.get_by_id(customer_id=customer_id)
    assert customer is not None
    price = Decimal(unit_price)
    order = Order(
        order_id=uuid4(),
        customer_id=customer_id,
        delivery_address=address if address is not None else customer.address,
        items=[
            OrderItem(
                item_id=uuid4(),
                product_id=product_id,
                quantity=quantity,
                unit="bag",
                unit_price=price,
                line_total=price * quantity,
            )
        ],
        currency="INR",
        subtotal=price * quantity,
        status=status,
        created_at=created_at,
        updated_at=created_at,
    )
    repos.orders.save(order=order)
    if dispatched:
        repos.dispatches.save(
            dispatch=Dispatch(
                dispatch_id=uuid4(),
                order_id=order.order_id,
                customer_id=customer_id,
                warehouse_id=WH_PEENYA_ID,
                status=DispatchStatus.DISPATCHED,
                delivery_address=order.delivery_address,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return order


# =========================================================================== #
# P2-A — business-level duplicate order detection
# =========================================================================== #


def test_exact_duplicate_of_an_executed_order_is_not_created_again() -> None:
    repos, orchestrator = _setup()
    first = orchestrator.process_text(text=KUMAR)
    _approve(orchestrator, first)
    existing = repos.orders.list_all()[0]

    second = orchestrator.process_text(text=KUMAR)

    assert second.decision is not None
    assert second.decision.decision is DecisionType.BLOCKED
    assert second.decision.reason_code is DecisionReasonCode.DUPLICATE_ORDER
    assert second.duplicate_check is not None
    assert second.duplicate_check.status is DuplicateStatus.DUPLICATE_FOUND
    assert second.duplicate_check.duplicate_order_ids == [existing.order_id]
    assert second.run.failure_code == "DUPLICATE_ORDER"
    assert str(existing.order_id) in second.message
    assert second.approval is None
    assert repos.pending_executions.list_by_run(run_id=second.run.run_id) == []
    assert _writes(repos) == (1, 0, 1)
    trace = orchestrator.trace_service.get_run_trace(run_id=second.run.run_id)
    assert trace is not None
    assert any("DUPLICATE_FOUND" in (e.output_summary or "") for e in trace.events)


@pytest.mark.parametrize(
    ("label", "second_text", "extra_quotes"),
    [
        ("different quantity", KUMAR_11, []),
        ("different customer", SHARMA_UT, []),
        (
            "different product",
            SHARMA_ACC,
            [
                Quote(
                    quote_id=uuid4(),
                    customer_id=CUST_SHARMA_BUILDERS_ID,
                    product_id=PROD_ACC_CEMENT_ID,
                    unit="bag",
                    unit_price=Decimal("400.00"),
                    currency="INR",
                    quoted_on=date(2026, 10, 1),
                    valid_until=date(2026, 12, 31),
                    status=QuoteStatus.VALID,
                    created_at=T,
                    updated_at=T,
                )
            ],
        ),
    ],
)
def test_orders_with_a_different_business_identity_remain_executable(
    label: str, second_text: str, extra_quotes: list[Quote]
) -> None:
    repos = SyntheticRepositories()
    repos.quotes = InMemoryQuoteRepository(get_synthetic_quotes() + extra_quotes)
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos, clock=lambda: T)
    first_text = SHARMA_UT if label == "different product" else KUMAR
    _approve(orchestrator, orchestrator.process_text(text=first_text))

    second = orchestrator.process_text(text=second_text)

    assert second.duplicate_check is not None, label
    assert second.duplicate_check.status is DuplicateStatus.NO_DUPLICATE, label
    assert second.approval is not None, label
    _approve(orchestrator, second)
    assert _writes(repos) == (2, 0, 2), label


def test_different_destination_is_not_a_duplicate() -> None:
    repos, orchestrator = _setup()
    _seed_order(repos, address="Warehouse 9, Tumkur Road")

    result = orchestrator.process_text(text=KUMAR)

    assert result.duplicate_check is not None
    assert result.duplicate_check.status is DuplicateStatus.NO_DUPLICATE
    _approve(orchestrator, result)
    assert len(repos.orders.list_all()) == 2


def test_completed_order_is_a_duplicate_only_on_the_same_business_day() -> None:
    repos, orchestrator = _setup()
    _seed_order(repos, created_at=T - timedelta(days=3), dispatched=True)

    older = orchestrator.process_text(text=KUMAR)

    assert older.duplicate_check is not None
    assert older.duplicate_check.status is DuplicateStatus.NO_DUPLICATE  # repeat business

    repos2, orchestrator2 = _setup()
    same_day = _seed_order(repos2, created_at=T - timedelta(hours=2), dispatched=True)
    today = orchestrator2.process_text(text=KUMAR)

    assert today.duplicate_check is not None
    assert today.duplicate_check.status is DuplicateStatus.DUPLICATE_FOUND
    assert today.duplicate_check.duplicate_order_ids == [same_day.order_id]
    assert today.approval is None and _writes(repos2) == (1, 0, 1)


@pytest.mark.parametrize(
    ("status", "duplicate"),
    [
        (OrderStatus.DRAFT, True),
        (OrderStatus.PENDING_APPROVAL, True),
        (OrderStatus.CONFIRMED, True),
        (OrderStatus.CANCELLED, False),
        (OrderStatus.FAILED, False),
    ],
)
def test_open_order_is_a_duplicate_whenever_it_was_placed(
    status: OrderStatus, duplicate: bool
) -> None:
    repos, orchestrator = _setup()
    _seed_order(repos, status=status, created_at=T - timedelta(days=10))

    result = orchestrator.process_text(text=KUMAR)

    assert result.duplicate_check is not None
    expected = DuplicateStatus.DUPLICATE_FOUND if duplicate else DuplicateStatus.NO_DUPLICATE
    assert result.duplicate_check.status is expected
    assert (result.approval is None) is duplicate
    assert len(repos.orders.list_all()) == 1


def test_duplicate_created_after_approval_request_is_caught_at_execution() -> None:
    repos, orchestrator = _setup()
    pending = orchestrator.process_text(text=KUMAR)
    # Another run places and executes the equivalent order in the meantime.
    _approve(orchestrator, orchestrator.process_text(text=KUMAR))
    assert _writes(repos) == (1, 0, 1)

    result = _approve(orchestrator, pending)

    assert result.decision is not None
    assert result.decision.reason_code is DecisionReasonCode.DUPLICATE_ORDER
    assert result.run.status is VoiceRunStatus.BLOCKED
    assert _writes(repos) == (1, 0, 1)  # no second order or dispatch
    assert pending.approval is not None
    approval = repos.approvals.get_by_id(approval_id=pending.approval.approval_id)
    assert approval is not None and approval.status is ApprovalStatus.EXPIRED
    assert approval.expiry_reason and "equivalent order" in approval.expiry_reason
    assert repos.tool_executions.list_by_run(run_id=pending.run.run_id) == []


def test_unreadable_order_store_is_never_treated_as_no_duplicate() -> None:
    repos, orchestrator = _setup()

    def broken(**_: Any) -> list[Order]:
        raise ConnectionError("orders database unavailable")

    repos.orders.list_by_customer = broken  # type: ignore[method-assign]

    result = orchestrator.process_text(text=KUMAR)

    assert result.duplicate_check is not None
    assert result.duplicate_check.status is DuplicateStatus.DUPLICATE_CHECK_UNAVAILABLE
    assert result.run.status is VoiceRunStatus.HANDOFF
    assert result.handoff_case is not None
    assert result.approval is None and _writes(repos) == (0, 0, 0)


def test_duplicate_detection_does_not_disturb_normal_execution() -> None:
    repos, orchestrator = _setup()

    processed = orchestrator.process_text(text=KUMAR)
    assert processed.duplicate_check is not None
    assert processed.duplicate_check.status is DuplicateStatus.NO_DUPLICATE
    executed = _approve(orchestrator, processed)

    assert executed.run.status is VoiceRunStatus.COMPLETED
    assert executed.duplicate_check is not None
    assert executed.duplicate_check.status is DuplicateStatus.NO_DUPLICATE
    assert _writes(repos) == (1, 0, 1)


# =========================================================================== #
# P2-B — approval audit metadata
# =========================================================================== #


def _fresh_api() -> AppContainer:
    return reset_container(clock=lambda: T)


def test_approval_records_run_plan_snapshot_and_actors() -> None:
    container = _fresh_api()
    repos = container.repositories
    run_id = client.post("/runs").json()["run_id"]
    body = client.post(f"/runs/{run_id}/process", json={"text": KUMAR}).json()
    approval_id = UUID(body["approval_id"])
    pending = repos.pending_executions.get_by_approval_id(approval_id=approval_id)
    approval = repos.approvals.get_by_id(approval_id=approval_id)
    assert pending is not None and approval is not None

    assert approval.run_id == UUID(run_id)
    assert approval.plan_id == pending.plan.plan_id
    assert approval.plan_fingerprint == pending.plan.fingerprint
    assert approval.snapshot_version == pending.plan.snapshot_version
    assert approval.requested_by is None  # no identity is invented
    assert approval.actor_authenticated is False
    assert approval.requested_at == T

    operator = uuid4()
    approved = client.post(
        f"/runs/{run_id}/approve",
        json={"approval_id": str(approval_id), "approved_by": str(operator)},
    )
    assert approved.status_code == 200
    final = repos.approvals.get_by_id(approval_id=approval_id)
    assert final is not None
    assert final.status is ApprovalStatus.APPROVED
    assert final.approved_by == operator and final.actor_authenticated is False
    assert final.resolved_at == T
    assert final.approved_snapshot_version == final.snapshot_version
    order = repos.orders.list_all()[0]
    dispatch = repos.dispatches.list_all()[0]
    assert final.order_id == order.order_id and final.dispatch_id == dispatch.dispatch_id


def test_approval_without_identity_records_none_not_a_fabricated_id() -> None:
    container = _fresh_api()
    run_id = client.post("/runs").json()["run_id"]
    body = client.post(f"/runs/{run_id}/process", json={"text": KUMAR}).json()

    client.post(f"/runs/{run_id}/approve", json={"approval_id": body["approval_id"]})

    approval = container.repositories.approvals.get_by_id(approval_id=UUID(body["approval_id"]))
    assert approval is not None
    assert approval.status is ApprovalStatus.APPROVED and approval.approved_by is None


def test_superseded_rejected_and_expired_approvals_keep_their_history() -> None:
    container = _fresh_api()
    repos = container.repositories
    user_headers = {"Authorization": f"Bearer {uuid4()}"}
    run_id = client.post("/runs", headers=user_headers).json()["run_id"]
    first = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR}, headers=user_headers
    ).json()
    second = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_11}, headers=user_headers
    ).json()

    superseded = repos.approvals.get_by_id(approval_id=UUID(first["approval_id"]))
    assert superseded is not None
    assert superseded.status is ApprovalStatus.SUPERSEDED
    assert superseded.superseded_by == UUID(second["approval_id"])
    assert superseded.resolved_at == T and superseded.run_id == UUID(run_id)

    rejector = uuid4()
    rejected = client.post(
        f"/runs/{run_id}/reject",
        json={
            "approval_id": second["approval_id"],
            "rejected_by": str(rejector),
            "reason": "Wrong site",
        },
    )
    assert rejected.status_code == 200
    record = repos.approvals.get_by_id(approval_id=UUID(second["approval_id"]))
    assert record is not None
    assert record.status is ApprovalStatus.REJECTED
    assert record.rejected_by == rejector and record.approved_by is None
    assert record.rejection_reason == "Wrong site" and record.resolved_at == T

    third = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR}, headers=user_headers
    ).json()
    for inventory in repos.inventory.list_all():
        inventory.reserved_quantity += 1  # business state changes before approval
    client.post(f"/runs/{run_id}/approve", json={"approval_id": third["approval_id"]})
    expired = repos.approvals.get_by_id(approval_id=UUID(third["approval_id"]))
    assert expired is not None
    assert expired.status is ApprovalStatus.EXPIRED
    assert expired.expiry_reason and "business state changed" in expired.expiry_reason
    assert expired.approved_snapshot_version != expired.snapshot_version
    assert _writes(repos) == (0, 0, 0)


def test_audit_identity_never_grants_authorization() -> None:
    container = _fresh_api()
    user_headers = {"Authorization": f"Bearer {uuid4()}"}
    run_id = client.post("/runs", headers=user_headers).json()["run_id"]
    first = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR}, headers=user_headers
    ).json()
    client.post(f"/runs/{run_id}/process", json={"text": KUMAR_11}, headers=user_headers)

    claimed_owner = client.post(
        f"/runs/{run_id}/approve",
        json={"approval_id": first["approval_id"], "approved_by": str(uuid4())},
    )
    forged = client.post(
        f"/runs/{run_id}/approve",
        json={"approval_id": first["approval_id"], "actor_authenticated": True},
    )

    assert claimed_owner.status_code == 409  # superseded stays superseded
    assert claimed_owner.json()["detail"]["code"] == "APPROVAL_SUPERSEDED"
    assert forged.status_code == 422
    assert _writes(container.repositories) == (0, 0, 0)


# =========================================================================== #
# P2-C — bound confirmation
# =========================================================================== #


def test_confirmation_is_bound_and_still_requires_approval() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.run.status is VoiceRunStatus.CONFIRMATION_REQUIRED
    assert asked.confirmation is not None and asked.approval is None
    assert "Confirm?" in asked.confirmation.prompt
    assert asked.confirmation.warning_keys == ["PRICE_CONSISTENCY|pricing.amount|400.00|1"]

    confirmed = orchestrator.confirm(
        run_id=asked.run.run_id,
        reply="Yes, confirm.",
        confirmation_id=asked.confirmation.confirmation_id,
    )

    record = repos.pending_confirmations.get_by_id(
        confirmation_id=asked.confirmation.confirmation_id
    )
    assert record is not None and record.status is ConfirmationStatus.CONFIRMED
    assert confirmed.run.status is VoiceRunStatus.APPROVAL_REQUIRED  # not executed
    assert confirmed.approval is not None
    assert confirmed.approval.status is ApprovalStatus.REQUESTED
    assert confirmed.plan is not None
    assert confirmed.plan.tool_calls[0].arguments["items"][0]["unit_price"] == "400.00"
    assert repos.tool_executions.list_by_run(run_id=asked.run.run_id) == []
    assert _writes(repos) == (0, 0, 0)

    _approve(orchestrator, confirmed)
    assert repos.orders.list_all()[0].items[0].unit_price == Decimal("400.00")  # quote, not ₹1


def test_confirmation_without_id_binds_to_the_runs_single_pending_confirmation() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)

    confirmed = orchestrator.confirm(run_id=asked.run.run_id, reply="haan theek hai")

    assert confirmed.approval is not None
    assert _writes(repos) == (0, 0, 0)


def test_confirmation_after_supersession_is_refused() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.confirmation is not None
    newer = orchestrator.process_text(text=KUMAR_RUPEE, run_id=asked.run.run_id)
    assert newer.superseded_confirmation_ids == [asked.confirmation.confirmation_id]

    with pytest.raises(ConfirmationFlowError) as excinfo:
        orchestrator.confirm(
            run_id=asked.run.run_id,
            reply="yes",
            confirmation_id=asked.confirmation.confirmation_id,
        )

    assert excinfo.value.code == "CONFIRMATION_SUPERSEDED"
    old = repos.pending_confirmations.get_by_id(confirmation_id=asked.confirmation.confirmation_id)
    assert newer.confirmation is not None
    assert old is not None and old.superseded_by == newer.confirmation.confirmation_id
    assert repos.approvals._approvals == {}  # nothing approvable was created
    assert _writes(repos) == (0, 0, 0)


def test_confirmation_with_nothing_pending_changes_nothing() -> None:
    repos, orchestrator = _setup()
    executed = _approve(orchestrator, orchestrator.process_text(text=KUMAR))

    reply = orchestrator.confirm(run_id=executed.run.run_id, reply="yes")

    assert reply.decision is not None and reply.decision.decision is DecisionType.CLARIFY
    assert reply.run.status is VoiceRunStatus.COMPLETED  # unchanged
    assert reply.approval is None
    assert _writes(repos) == (1, 0, 1)


def test_declined_confirmation_cannot_be_confirmed_later() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.confirmation is not None

    declined = orchestrator.confirm(run_id=asked.run.run_id, reply="nahi")
    assert declined.run.status is VoiceRunStatus.BLOCKED
    assert declined.run.failure_code == "CONFIRMATION_DECLINED"

    with pytest.raises(ConfirmationFlowError) as excinfo:
        orchestrator.confirm(
            run_id=asked.run.run_id,
            reply="yes",
            confirmation_id=asked.confirmation.confirmation_id,
        )
    assert excinfo.value.code == "CONFIRMATION_NOT_PENDING"
    assert repos.approvals._approvals == {}
    assert _writes(repos) == (0, 0, 0)


def test_confirmation_for_another_run_is_refused() -> None:
    repos, orchestrator = _setup()
    run_a = orchestrator.process_text(text=KUMAR_RUPEE)
    run_b = orchestrator.process_text(text=KUMAR_RUPEE)
    assert run_a.confirmation is not None

    with pytest.raises(ConfirmationFlowError) as excinfo:
        orchestrator.confirm(
            run_id=run_b.run.run_id,
            reply="yes",
            confirmation_id=run_a.confirmation.confirmation_id,
        )

    assert excinfo.value.code == "CONFIRMATION_RUN_MISMATCH"
    record = repos.pending_confirmations.get_by_id(
        confirmation_id=run_a.confirmation.confirmation_id
    )
    assert record is not None and record.status is ConfirmationStatus.REQUESTED
    assert _writes(repos) == (0, 0, 0)


def test_confirmation_after_business_state_changed_expires() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.confirmation is not None
    quote = repos.quotes.get_by_id(quote_id=QUOTE_KUMAR_ACC_VALID_ID)
    assert quote is not None
    quote.unit_price = Decimal("410.00")  # the quote changed after the user was asked

    result = orchestrator.confirm(run_id=asked.run.run_id, reply="yes")

    old = repos.pending_confirmations.get_by_id(confirmation_id=asked.confirmation.confirmation_id)
    assert old is not None and old.status is ConfirmationStatus.EXPIRED
    assert result.confirmation is not None  # asked again, about the new facts
    assert result.confirmation.confirmation_id != old.confirmation_id
    assert result.confirmation.warning_keys == ["PRICE_CONSISTENCY|pricing.amount|410.00|1"]
    assert result.approval is None and _writes(repos) == (0, 0, 0)


def test_unclear_reply_keeps_the_confirmation_pending() -> None:
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.confirmation is not None

    result = orchestrator.confirm(run_id=asked.run.run_id, reply="haan, mat karo")

    record = repos.pending_confirmations.get_by_id(
        confirmation_id=asked.confirmation.confirmation_id
    )
    assert record is not None and record.status is ConfirmationStatus.REQUESTED
    assert result.approval is None and _writes(repos) == (0, 0, 0)


def test_confirm_endpoint_answers_only_the_bound_confirmation() -> None:
    container = _fresh_api()
    run_id = client.post("/runs").json()["run_id"]
    asked = client.post(f"/runs/{run_id}/process", json={"text": KUMAR_RUPEE}).json()
    assert asked["status"] == "CONFIRMATION_REQUIRED"
    assert asked["approval_id"] is None and asked["approval_required"] is False
    confirmation_id = asked["confirmation"]["confirmation_id"]

    bypass = client.post(f"/runs/{run_id}/confirm", json={"reply": "yes", "is_approved": True})
    unknown = client.post(
        f"/runs/{run_id}/confirm", json={"reply": "yes", "confirmation_id": str(uuid4())}
    )
    ok = client.post(
        f"/runs/{run_id}/confirm", json={"reply": "yes", "confirmation_id": confirmation_id}
    )

    assert bypass.status_code == 422
    assert unknown.status_code == 404
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVAL_REQUIRED"
    assert ok.json()["approval_id"] is not None
    assert _writes(container.repositories) == (0, 0, 0)


# =========================================================================== #
# P2-D — operator resolution of UNKNOWN
# =========================================================================== #


def _unknown_order(
    container: AppContainer,
) -> tuple[str, Any]:
    orchestrator = container.orchestrator
    processed = orchestrator.process_text(text=KUMAR)
    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"create_order": "before_commit"}}
    )
    assert result.run.status is VoiceRunStatus.HANDOFF
    execution = container.repositories.tool_executions.list_by_run(run_id=result.run.run_id)[0]
    assert execution.status is ToolExecutionStatus.UNKNOWN
    return str(result.run.run_id), execution


def _late_commit(container: AppContainer, execution: Any) -> UUID:
    """The business system commits the order after the client timed out."""
    tool_result = CreateOrderTool().execute(
        arguments=execution.arguments,
        context=ToolContext(
            run_id=execution.run_id,
            repositories=container.repositories,
            idempotency_key=execution.idempotency_key,
            now=T,
        ),
    )
    assert tool_result.success
    return UUID(tool_result.data["order_id"])


def _resolve(run_id: str, execution_id: Any, **body: Any) -> Any:
    payload = {"attempt": 1, "outcome": "SUCCEEDED", "reason": "Checked the ERP", **body}
    return client.post(f"/runs/{run_id}/executions/{execution_id}/resolve", json=payload)


def test_operator_resolves_unknown_to_success_only_with_a_verified_record() -> None:
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    order_id = _late_commit(container, execution)
    operator = uuid4()

    response = _resolve(run_id, execution.execution_id, resolved_by=str(operator))

    assert response.status_code == 200
    body = response.json()
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None
    assert record.status is ToolExecutionStatus.SUCCEEDED
    assert record.resolution == "OPERATOR_CONFIRMED_SUCCESS"
    assert record.resolved_by == operator and record.resolved_at == T
    assert record.resolution_reason == "Checked the ERP"
    assert record.prior_status is ToolExecutionStatus.UNKNOWN  # history kept
    assert record.prior_error_code == "TOOL_TIMEOUT" and record.prior_error_message
    assert record.attempt == 1
    verifications = container.repositories.verifications.get_by_execution_id(
        execution_id=execution.execution_id
    )
    assert verifications is not None and verifications.status is VerificationStatus.VERIFIED
    # The resolution never runs the remaining steps.
    assert body["status"] == "HANDOFF"
    assert [(o["tool_name"], o["status"]) for o in body["tool_outcomes"]] == [
        ("create_order", "VERIFIED"),
        ("dispatch_order", "NOT_ATTEMPTED"),
    ]
    assert _writes(container.repositories) == (1, 0, 0)
    approval = next(iter(container.repositories.approvals._approvals.values()))
    assert approval.order_id == order_id


def test_operator_resolves_unknown_to_failure() -> None:
    container = _fresh_api()
    run_id, execution = _unknown_order(container)

    response = _resolve(run_id, execution.execution_id, outcome="FAILED")

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None
    assert record.status is ToolExecutionStatus.FAILED
    assert record.resolution == "OPERATOR_CONFIRMED_FAILURE"
    assert record.prior_status is ToolExecutionStatus.UNKNOWN
    assert record.prior_error_code == "TOOL_TIMEOUT"
    assert _writes(container.repositories) == (0, 0, 0)


def test_success_cannot_be_recorded_for_an_operation_that_never_wrote() -> None:
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    unrelated = _seed_order(container.repositories)  # same content, different operation

    nothing = _resolve(run_id, execution.execution_id)
    other = _resolve(run_id, execution.execution_id, entity_id=str(unrelated.order_id))

    assert (
        nothing.status_code == 409 and nothing.json()["detail"]["code"] == "RESOLUTION_NOT_VERIFIED"
    )
    assert other.status_code == 409 and other.json()["detail"]["code"] == "RESOLUTION_NOT_VERIFIED"
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None and record.status is ToolExecutionStatus.UNKNOWN


def test_failure_cannot_be_recorded_when_a_record_was_committed() -> None:
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    _late_commit(container, execution)

    response = _resolve(run_id, execution.execution_id, outcome="FAILED")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESOLUTION_CONTRADICTED"
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None and record.status is ToolExecutionStatus.UNKNOWN


def test_resolution_refuses_wrong_stale_or_already_resolved_operations() -> None:
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    _, other_execution = _unknown_order(container)

    missing = _resolve(run_id, uuid4(), outcome="FAILED")
    wrong_run = _resolve(run_id, other_execution.execution_id, outcome="FAILED")
    stale = _resolve(run_id, execution.execution_id, outcome="FAILED", attempt=2)
    first = _resolve(run_id, execution.execution_id, outcome="FAILED")
    again = _resolve(run_id, execution.execution_id, outcome="FAILED")
    bypass = _resolve(run_id, execution.execution_id, outcome="FAILED", status="SUCCEEDED")

    assert missing.status_code == 404
    assert wrong_run.json()["detail"]["code"] == "EXECUTION_RUN_MISMATCH"
    assert stale.json()["detail"]["code"] == "STALE_RESOLUTION"
    assert first.status_code == 200
    assert again.json()["detail"]["code"] == "ALREADY_RESOLVED"
    assert bypass.status_code == 422
    untouched = container.repositories.tool_executions.get_by_id(
        execution_id=other_execution.execution_id
    )
    assert untouched is not None and untouched.status is ToolExecutionStatus.UNKNOWN


def test_a_verified_execution_cannot_be_resolved() -> None:
    container = _fresh_api()
    orchestrator = container.orchestrator
    executed = _approve(orchestrator, orchestrator.process_text(text=KUMAR))
    execution = container.repositories.tool_executions.list_by_run(run_id=executed.run.run_id)[0]

    response = _resolve(str(executed.run.run_id), execution.execution_id, outcome="FAILED")

    assert response.json()["detail"]["code"] == "NOT_UNKNOWN"
    assert _writes(container.repositories) == (1, 0, 1)


# =========================================================================== #
# P2-E — end-to-end audit linkage
# =========================================================================== #


def test_completed_canonical_run_is_auditable_end_to_end() -> None:
    _fresh_api()
    run_id = client.post("/runs").json()["run_id"]
    body = client.post(f"/runs/{run_id}/process", json={"text": CANONICAL}).json()
    operator = uuid4()
    client.post(
        f"/runs/{run_id}/approve",
        json={"approval_id": body["approval_id"], "approved_by": str(operator)},
    )

    audit = client.get(f"/runs/{run_id}/audit").json()

    # What did the user request, and what was understood?
    assert audit["instructions"][0]["text"] == CANONICAL
    understood = audit["instructions"][0]["understood"]
    assert understood["customer"] == "sharma builders"
    assert {r["surface"] for r in understood["references"]} >= {"Rate wahi"}
    # What plan, context and validation; why approval; what was approved, by whom?
    plan = audit["plans"][0]
    assert plan["approval"]["approval_id"] == body["approval_id"]
    assert plan["approval"]["status"] == "APPROVED"
    assert plan["approval"]["approved_by"] == str(operator)
    assert plan["approval"]["plan_fingerprint"] == plan["fingerprint"]
    assert plan["approval_required_because"]
    quotes = plan["resolved_context"]["quotes"]
    assert [q["quote"]["quote_id"] for q in quotes] == [str(QUOTE_SHARMA_ULTRATECH_VALID_ID)]
    assert plan["validation"]["status"] == "PASSED"
    # What changed between approval and execution?
    assert plan["changed_between_approval_and_execution"]["changed"] is False
    # What ran, what did it return, what was verified, what is the business state?
    executions = audit["tool_executions"]
    assert [e["tool_name"] for e in executions] == [
        "create_order",
        "create_invoice_draft",
        "dispatch_order",
    ]
    assert all(e["status"] == "SUCCEEDED" and e["result"] for e in executions)
    assert [v["status"] for v in audit["verifications"]] == ["VERIFIED"] * 3
    assert {v["execution_id"] for v in audit["verifications"]} == {
        e["execution_id"] for e in executions
    }
    records = audit["business_records"]
    order = records["orders"][0]
    assert order["order_id"] == plan["approval"]["order_id"]
    assert records["invoices"][0]["order_id"] == order["order_id"]
    assert records["dispatches"][0]["order_id"] == order["order_id"]
    assert records["dispatches"][0]["dispatch_id"] == plan["approval"]["dispatch_id"]
    assert audit["handoffs"][0]["blocked_actions"] == ["SEND_NOTIFICATION"]
    stages = [e["stage"] for e in audit["trace"]]
    for stage in ("APPROVAL_REQUESTED", "DUPLICATE_CHECKED", "APPROVED", "VERIFIED"):
        assert stage in stages
    assert audit["run"]["status"] == "HANDOFF"


# =========================================================================== #
# P2-F — status and wording derived from actual state
# =========================================================================== #

_FORBIDDEN_CLAIMS = ("remains confirmed", "confirmed with warehouse", "created successfully")


def _no_false_claims(message: str) -> None:
    for claim in _FORBIDDEN_CLAIMS:
        assert claim not in message


def test_draft_only_order_is_described_as_a_draft() -> None:
    repos, orchestrator = _setup()
    result = _approve(orchestrator, orchestrator.process_text(text=SHARMA_ORDER_ONLY))

    order = repos.orders.list_all()[0]
    assert order.status is OrderStatus.DRAFT
    assert f"order {order.order_id} DRAFT" in result.message
    assert "dispatch" not in result.message.lower()
    _no_false_claims(result.message)


def test_status_and_wording_follow_execution_state() -> None:
    repos, orchestrator = _setup()
    requested = orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH)
    assert requested.run.status is VoiceRunStatus.APPROVAL_REQUIRED
    assert "Nothing has been executed" in requested.message
    assert _writes(repos) == (0, 0, 0)

    done = _approve(orchestrator, requested)
    order, invoice, dispatch = (
        repos.orders.list_all()[0],
        repos.invoices.list_all()[0],
        repos.dispatches.list_all()[0],
    )
    assert done.run.status is VoiceRunStatus.COMPLETED
    assert f"order {order.order_id} DRAFT" in done.message
    assert f"invoice {invoice.invoice_id} DRAFT" in done.message
    assert f"dispatch {dispatch.dispatch_id} DISPATCHED" in done.message
    _no_false_claims(done.message)


def test_partial_failed_and_unknown_wording_never_overstates() -> None:
    repos, orchestrator = _setup()
    partial = _approve(
        orchestrator,
        orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH),
        faults={"simulate_dispatch_failure": True},
    )
    assert partial.run.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert "no dispatch was recorded" in partial.message
    assert repos.dispatches.list_all() == []
    _no_false_claims(partial.message)

    repos2, orchestrator2 = _setup()
    unknown = _approve(
        orchestrator2,
        orchestrator2.process_text(text=SHARMA_INVOICE_DISPATCH),
        faults={"simulate_timeout": {"create_order": "before_commit"}},
    )
    assert unknown.run.status is VoiceRunStatus.HANDOFF
    assert "Outcome unknown" in unknown.message and "Executed" not in unknown.message
    assert _writes(repos2) == (0, 0, 0)

    repos3, orchestrator3 = _setup()
    expired_request = orchestrator3.process_text(text=SHARMA_INVOICE_DISPATCH)
    for inventory in repos3.inventory.list_all():
        inventory.reserved_quantity += 1
    expired = _approve(orchestrator3, expired_request)
    assert expired.run.status is VoiceRunStatus.FAILED
    assert "Nothing was executed" in expired.message
    assert _writes(repos3) == (0, 0, 0)


def test_clarification_and_confirmation_states_create_no_approval() -> None:
    repos, orchestrator = _setup()
    clarify = orchestrator.process_text(
        text="Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo."
    )
    confirm = orchestrator.process_text(text=KUMAR_RUPEE)

    assert clarify.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert confirm.run.status is VoiceRunStatus.CONFIRMATION_REQUIRED
    assert clarify.approval is None and confirm.approval is None
    assert repos.approvals._approvals == {}
    assert _writes(repos) == (0, 0, 0)


# =========================================================================== #
# P2-G — verification contracts
# =========================================================================== #


def test_every_write_tool_has_a_contract_or_is_explicitly_unplannable() -> None:
    writes = {
        tool.name
        for tool in create_default_registry().list_tools()
        if tool.side_effect is not ToolSideEffect.READ_ONLY
    }
    assert writes == set(VERIFICATION_CONTRACTS) | set(UNPLANNABLE_WRITE_TOOLS)
    assert not set(VERIFICATION_CONTRACTS) & set(UNPLANNABLE_WRITE_TOOLS)
    with pytest.raises(PlanningError):
        expected_state_for("issue_invoice", {"invoice_id": str(uuid4())})


def test_a_write_tool_without_a_contract_is_never_planned(monkeypatch: pytest.MonkeyPatch) -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH)
    assert processed.understand_result is not None and processed.business_context is not None
    monkeypatch.setitem(
        plan_module.ACTION_TOOLS,
        plan_module.RequestedActionType.CREATE_INVOICE_DRAFT,
        ("create_order", "issue_invoice"),
    )

    with pytest.raises(PlanningError, match="issue_invoice"):
        build_plan(
            run_id=processed.run.run_id,
            semantic_state=processed.understand_result.semantic_state,
            business_context=processed.business_context,
            tax_calculation=None,
        )
    blocked = orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH)
    assert blocked.decision is not None and blocked.decision.decision is DecisionType.BLOCKED
    assert _writes(repos) == (0, 0, 0)


def test_a_step_without_a_contract_at_execution_is_not_invoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vaaniflow.application.services import orchestrator as orchestrator_module

    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH)
    real = orchestrator_module.expected_state_for

    def without_dispatch_contract(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "dispatch_order":
            raise PlanningError("No read-back verification contract (test).")
        return real(tool_name, arguments)

    monkeypatch.setattr(orchestrator_module, "expected_state_for", without_dispatch_contract)

    result = _approve(orchestrator, processed)

    assert [(s.tool_name, s.status) for s in result.step_outcomes] == [
        ("create_order", StepStatus.VERIFIED),
        ("create_invoice_draft", StepStatus.VERIFIED),
        ("dispatch_order", StepStatus.FAILED),
    ]
    assert result.step_outcomes[2].error_code == "NO_VERIFICATION_CONTRACT"
    assert result.run.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert _writes(repos) == (1, 1, 0)
    tools = [e.tool_name for e in repos.tool_executions.list_by_run(run_id=result.run.run_id)]
    assert "dispatch_order" not in tools  # never invoked


# =========================================================================== #
# P2-H — quote semantics
# =========================================================================== #


def _with_quotes(quotes: list[Quote]) -> tuple[SyntheticRepositories, VoiceWorkflowOrchestrator]:
    repos = SyntheticRepositories()
    repos.quotes = InMemoryQuoteRepository(quotes)
    return repos, VoiceWorkflowOrchestrator(repositories=repos, clock=lambda: T)


def _quote(quoted_on: date, price: str, until: date | None, status: QuoteStatus) -> Quote:
    return Quote(
        quote_id=uuid4(),
        customer_id=CUST_SHARMA_BUILDERS_ID,
        product_id=PROD_ULTRATECH_CEMENT_ID,
        unit="bag",
        unit_price=Decimal(price),
        currency="INR",
        quoted_on=quoted_on,
        valid_until=until,
        status=status,
        created_at=T,
        updated_at=T,
    )


SAME_RATE = "Sharma Builders ko 200 bags UltraTech cement ka invoice banao, same rate."


def test_accepted_quote_is_not_executable_pricing() -> None:
    """ACCEPTED has no defined pricing semantics in the model; it stays non-executable."""
    repos, orchestrator = _with_quotes([_quote(D, "420", date(2026, 11, 15), QuoteStatus.ACCEPTED)])

    result = orchestrator.process_text(text=CANONICAL)

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.business_context is not None and result.business_context.resolved_price is None
    assert result.approval is None and _writes(repos) == (0, 0, 0)


def test_undated_reference_uses_the_single_applicable_quote() -> None:
    valid = _quote(date(2026, 10, 1), "415", date(2026, 12, 31), QuoteStatus.VALID)
    stale = _quote(date(2026, 9, 1), "390", date(2026, 9, 30), QuoteStatus.VALID)
    _, orchestrator = _with_quotes([stale, valid])

    result = orchestrator.process_text(text=SAME_RATE)

    assert result.business_context is not None
    assert result.business_context.resolved_price is not None
    assert result.business_context.resolved_price.source_quote_id == valid.quote_id
    assert result.approval is not None


@pytest.mark.parametrize(
    ("quotes", "decision"),
    [
        (
            [
                _quote(date(2026, 10, 1), "415", date(2026, 12, 31), QuoteStatus.VALID),
                _quote(date(2026, 10, 10), "418", date(2026, 12, 31), QuoteStatus.VALID),
            ],
            DecisionType.CLARIFY,  # two applicable quotes: never ranked
        ),
        (
            [_quote(date(2026, 9, 1), "390", date(2026, 9, 30), QuoteStatus.VALID)],
            DecisionType.HUMAN_HANDOFF,  # only a lapsed quote
        ),
    ],
)
def test_undated_reference_without_a_single_applicable_quote_is_safe(
    quotes: list[Quote], decision: DecisionType
) -> None:
    repos, orchestrator = _with_quotes(quotes)

    result = orchestrator.process_text(text=SAME_RATE)

    assert result.decision is not None and result.decision.decision is decision
    assert result.approval is None and _writes(repos) == (0, 0, 0)


def test_expired_referenced_quote_is_preserved_and_not_substituted() -> None:
    referenced = _quote(D, "420", date(2026, 10, 16), QuoteStatus.VALID)  # lapsed on 10-17
    current = _quote(date(2026, 10, 16), "425", date(2026, 12, 31), QuoteStatus.VALID)
    repos, orchestrator = _with_quotes([referenced, current])

    result = orchestrator.process_text(text=CANONICAL)

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.business_context is not None
    assert [q.quote.quote_id for q in result.business_context.quotes] == [referenced.quote_id]
    assert result.business_context.resolved_price is None  # the current quote is not used
    case = result.handoff_case
    assert case is not None
    assert any(str(referenced.quote_id) in e for e in case.evidence)
    assert any(r["surface"] == "Rate wahi" for r in case.interpreted_request["references"])
    assert any(t["surface"] == "parso" for t in case.interpreted_request["temporal_expressions"])
    assert result.approval is None and _writes(repos) == (0, 0, 0)


# =========================================================================== #
# P2-I — the price's own reference decides the temporal anchor
# =========================================================================== #


def _canonical_state_with_extra_reference(*, point_price_at_extra: bool) -> Any:
    _, orchestrator = _setup()
    processed = orchestrator.process_text(text=CANONICAL)
    assert processed.understand_result is not None
    state = processed.understand_result.semantic_state
    parso = state.temporal_expressions[0]
    rate_ref = state.references[0]
    kal = parso.model_copy(
        update={
            "expression_id": uuid4(),
            "surface_text": "kal",
            "normalized_expression": "DAY_OFFSET:-1",
            "day_offset": -1,
        }
    )
    other_ref = rate_ref.model_copy(
        update={
            "reference_id": uuid4(),
            "surface_text": "kal wala rate",
            "temporal_expression_id": kal.expression_id,
        }
    )
    pricing = state.pricing
    if point_price_at_extra:
        pricing = [p.model_copy(update={"reference_id": other_ref.reference_id}) for p in pricing]
    # The unrelated reference and expression come FIRST in the state.
    return orchestrator, state.model_copy(
        update={
            "temporal_expressions": [kal, *state.temporal_expressions],
            "references": [other_ref, *state.references],
            "pricing": pricing,
        }
    )


def test_quote_resolution_follows_the_reference_the_price_points_to() -> None:
    orchestrator, state = _canonical_state_with_extra_reference(point_price_at_extra=False)
    assert state.references[0].reference_type is ReferenceType.HISTORICAL_PRICE

    output = orchestrator.context_resolver.resolve(
        semantic_state=state, run_id=uuid4(), run_timestamp=T
    )

    # pricing[0] → "Rate wahi" → parso (2026-10-15), not the first link ("kal", 10-16).
    assert [q.quote.quote_id for q in output.business_context.quotes] == [
        QUOTE_SHARMA_ULTRATECH_VALID_ID
    ]


def test_price_pointing_at_the_other_reference_uses_its_date() -> None:
    orchestrator, state = _canonical_state_with_extra_reference(point_price_at_extra=True)

    output = orchestrator.context_resolver.resolve(
        semantic_state=state, run_id=uuid4(), run_timestamp=T
    )

    assert output.business_context.quotes == []  # no quote was given on 10-16
    assert output.business_context.resolved_price is None
    assert any("2026-10-16" in e for e in output.business_context.resolution_errors)


def test_conflicting_links_without_a_price_pointer_are_not_guessed() -> None:
    orchestrator, state = _canonical_state_with_extra_reference(point_price_at_extra=False)
    # No price slot points at a reference: both linked references are candidates,
    # and their dates (10-15 vs 10-16) disagree.
    unbound = state.model_copy(update={"pricing": []})

    output = orchestrator.context_resolver.resolve(
        semantic_state=unbound, run_id=uuid4(), run_timestamp=T
    )

    assert output.business_context.resolved_price is None
    assert any("could not be resolved" in e for e in output.business_context.resolution_errors)


# =========================================================================== #
# P2-J — clarification and handoff preserve the request
# =========================================================================== #


def test_clarification_preserves_what_was_understood_and_what_is_missing() -> None:
    container = _fresh_api()
    repos = container.repositories
    user_headers = {"Authorization": f"Bearer {uuid4()}"}
    run_id = client.post("/runs", headers=user_headers).json()["run_id"]

    body = client.post(
        f"/runs/{run_id}/process",
        json={"text": "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo, parso."},
        headers=user_headers,
    ).json()

    view = body["clarification"]
    assert view is not None and body["status"] == "CLARIFICATION_REQUIRED"
    ambiguity = next(u for u in view["unresolved"] if u["source"] == "SEMANTIC_AMBIGUITY")
    assert ambiguity["candidates"] == ["UltraTech cement", "ACC cement"]
    assert view["understood"]["customer"] == "sharma builders"
    assert "DISPATCH" in view["understood"]["actions"]
    assert view["understood"]["temporal_expressions"]
    record = repos.clarifications.get_by_id(clarification_id=UUID(view["clarification_id"]))
    assert record is not None and record.status is ClarificationStatus.OPEN
    assert record.understand_result.transcript.text.startswith("Sharma Builders ko 200 bags")

    followup = client.post(
        f"/runs/{run_id}/clarify", json={"clarification": KUMAR}, headers=user_headers
    ).json()

    assert followup["superseded_clarification_ids"] == [view["clarification_id"]]
    record = repos.clarifications.get_by_id(clarification_id=UUID(view["clarification_id"]))
    assert record is not None and record.status is ClarificationStatus.SUPERSEDED
    assert record.superseded_by_transcript_id is not None
    assert followup["approval_id"] is not None
    assert _writes(repos) == (0, 0, 0)


def test_business_level_clarification_lists_the_failed_checks() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text="Send 200 bags to Sharma.")

    assert result.clarification is not None
    sources = {u["source"] for u in result.clarification.unresolved}
    assert sources & {"VALIDATION", "INPUT_EVALUATION", "CONTEXT_RESOLUTION"}
    assert repos.clarifications.list_by_run(run_id=result.run.run_id) == [result.clarification]


def test_unknown_handoff_packet_carries_plan_approval_and_steps() -> None:
    _, orchestrator = _setup()
    processed = orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH)

    result = _approve(
        orchestrator,
        processed,
        faults={"simulate_timeout": {"create_invoice_draft": "before_commit"}},
    )

    case = result.handoff_case
    assert case is not None and processed.plan is not None and processed.approval is not None
    assert case.interpreted_request["plan_id"] == str(processed.plan.plan_id)
    assert case.interpreted_request["approval_id"] == str(processed.approval.approval_id)
    assert [s["status"] for s in case.interpreted_request["steps"]] == [
        "VERIFIED",
        "UNKNOWN",
        "NOT_ATTEMPTED",
    ]
    assert case.uncertainties and case.evidence


# =========================================================================== #
# P2 cleanup — F1 guidance, F4 late commit, F3 binding/label coverage
# =========================================================================== #


def test_resolution_guidance_matches_what_the_system_will_actually_do() -> None:
    """F1: after a verified create_order, re-sending the request is a duplicate."""
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    _late_commit(container, execution)

    resolved = _resolve(run_id, execution.execution_id).json()

    message = resolved["message"]
    assert "new instruction and approval are required" not in message
    assert "manually" in message and "dispatch_order" in message
    assert "duplicate" in message
    assert resolved["status"] == "HANDOFF"
    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.failure_code == "REMAINING_STEPS_NOT_ATTEMPTED"
    assert _writes(container.repositories) == (1, 0, 0)  # dispatch not run

    # Following the old advice is refused exactly as the new guidance says.
    user_headers = {"Authorization": f"Bearer {uuid4()}"}
    retry = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR}, headers=user_headers
    ).json()
    assert retry["status"] == "BLOCKED"
    assert retry["duplicate_check"]["status"] == "DUPLICATE_FOUND"
    assert _writes(container.repositories) == (1, 0, 0)
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None
    assert record.resolution == "OPERATOR_CONFIRMED_SUCCESS"
    assert record.prior_status is ToolExecutionStatus.UNKNOWN


def test_late_commit_after_failed_resolution_is_reported_as_a_contradiction() -> None:
    """F4: history is kept, the contradiction is surfaced, nothing is re-created."""
    container = _fresh_api()
    run_id, execution = _unknown_order(container)
    assert _resolve(run_id, execution.execution_id, outcome="FAILED").status_code == 200
    order_id = _late_commit(container, execution)  # the business system commits late

    audit = client.get(f"/runs/{run_id}/audit").json()

    reconciliation = audit["reconciliation"]
    assert reconciliation["consistent"] is False
    assert reconciliation["contradictions"] == [
        {
            "code": "FAILED_BUT_RECORD_EXISTS",
            "execution_id": str(execution.execution_id),
            "tool_name": "create_order",
            "recorded_status": "FAILED",
            "resolution": "OPERATOR_CONFIRMED_FAILURE",
            "resolved_by": None,
            "committed_record_id": str(order_id),
            "message": reconciliation["contradictions"][0]["message"],
        }
    ]
    record = container.repositories.tool_executions.get_by_id(execution_id=execution.execution_id)
    assert record is not None  # the operator's resolution is not rewritten
    assert record.status is ToolExecutionStatus.FAILED
    assert record.resolution == "OPERATOR_CONFIRMED_FAILURE"
    assert record.prior_status is ToolExecutionStatus.UNKNOWN

    retry = client.post("/runs", json={}).json()["run_id"]
    blocked = client.post(f"/runs/{retry}/process", json={"text": KUMAR}).json()
    assert blocked["duplicate_check"]["status"] == "DUPLICATE_FOUND"
    assert _writes(container.repositories) == (1, 0, 0)  # no second order, no retry

    clean_run = client.post("/runs").json()["run_id"]
    body = client.post(f"/runs/{clean_run}/process", json={"text": SHARMA_UT}).json()
    client.post(f"/runs/{clean_run}/approve", json={"approval_id": body["approval_id"]})
    clean = client.get(f"/runs/{clean_run}/audit").json()["reconciliation"]
    assert clean == {"consistent": True, "contradictions": []}


def test_confirmation_accepts_only_its_own_warning_keys_on_an_unchanged_snapshot() -> None:
    """F3-A: same business snapshot, different warning set → not accepted."""
    repos, orchestrator = _setup()
    asked = orchestrator.process_text(text=KUMAR_RUPEE)
    assert asked.confirmation is not None
    real_keys = asked.confirmation.warning_keys
    foreign = asked.confirmation.model_copy(
        update={"warning_keys": ["PRICE_CONSISTENCY|pricing.amount|400.00|999"]}
    )
    repos.pending_confirmations.save(confirmation=foreign)  # snapshot left unchanged

    result = orchestrator.confirm(run_id=asked.run.run_id, reply="yes")

    assert result.approval is None  # the foreign "yes" does not cover the real warning
    assert result.run.status is VoiceRunStatus.CONFIRMATION_REQUIRED
    assert result.confirmation is not None
    assert result.confirmation.warning_keys == real_keys
    assert result.confirmation.confirmation_id != asked.confirmation.confirmation_id
    assert repos.approvals._approvals == {}
    assert _writes(repos) == (0, 0, 0)


def test_unknown_step_is_never_labelled_failed() -> None:
    """F3-B: the per-step summary keeps UNKNOWN distinct from FAILED."""
    repos, orchestrator = _setup()
    result = _approve(
        orchestrator,
        orchestrator.process_text(text=SHARMA_INVOICE_DISPATCH),
        faults={"simulate_timeout": {"create_invoice_draft": "before_commit"}},
    )

    assert "Outcome unknown: create_invoice_draft." in result.message
    assert "Failed: create_invoice_draft" not in result.message
    assert "Not attempted: dispatch_order." in result.message
    assert [(s.tool_name, s.status) for s in result.step_outcomes][1] == (
        "create_invoice_draft",
        StepStatus.UNKNOWN,
    )
    assert _writes(repos) == (1, 0, 0)
