"""
Phase B P1 regressions: approval lifecycle, temporal quote grounding, price
authority, UNKNOWN tool outcomes, partial execution and read-back verification.

Every test inspects repository state, not only returned statuses.
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
from vaaniflow.api.routers.runs import _to_response
from vaaniflow.application.services.orchestrator import (
    ApprovalFlowError,
    VoiceWorkflowOrchestrator,
    WorkflowResult,
)
from vaaniflow.context.models.business_context import ResolvedCustomer, ResolvedProduct
from vaaniflow.context.models.resolution import ResolutionStatus
from vaaniflow.context.resolvers.quote import PriceQuoteResolver
from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.order import Order
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus, ToolSideEffect
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import Decision, DecisionReasonCode, DecisionType
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    PriceSource,
    ReferenceType,
    SemanticPrice,
    SemanticReference,
    SemanticSlot,
    TextSpan,
)
from vaaniflow.execution.plan import PlanningError, StepStatus, build_plan
from vaaniflow.execution.service import ExecutionService
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult
from vaaniflow.execution.tools.create_order import CreateOrderTool
from vaaniflow.execution.tools.registry import ToolRegistry, create_default_registry
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_KUMAR_CONSTRUCTIONS_ID,
    CUST_SHARMA_BUILDERS_ID,
    PROD_ULTRATECH_CEMENT_ID,
    QUOTE_KUMAR_ACC_VALID_ID,
    QUOTE_SHARMA_ULTRATECH_VALID_ID,
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)

NOW = SYNTHETIC_BUSINESS_TIME  # 2026-10-17 12:00 IST; "parso" = 2026-10-15

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)
KUMAR_DISPATCH = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
SHARMA_DISPATCH = (
    "Send 200 bags of UltraTech cement to Sharma Builders at the rate quoted "
    "day before yesterday and dispatch."
)
SHARMA_INVOICE_AND_DISPATCH = (
    "Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka invoice banao aur dispatch karo."
)

client = TestClient(app)


def _setup(
    registry: ToolRegistry | None = None,
) -> tuple[SyntheticRepositories, VoiceWorkflowOrchestrator]:
    repos = SyntheticRepositories()
    service = ExecutionService(repos, registry=registry) if registry else None
    return repos, VoiceWorkflowOrchestrator(repositories=repos, execution_service=service)


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
    now: datetime = NOW,
) -> WorkflowResult:
    assert result.approval is not None
    return orchestrator.approve(
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        approved_by=uuid4(),
        simulated_faults=faults,
        now=now,
    )


def _steps(result: WorkflowResult) -> dict[str, StepStatus]:
    return {step.tool_name: step.status for step in result.step_outcomes}


def _requested_approvals(repos: SyntheticRepositories, run_id: Any) -> list[Approval]:
    approvals = []
    for pending in repos.pending_executions.list_by_run(run_id=run_id):
        approval = repos.approvals.get_by_id(approval_id=pending.approval_id)
        if approval is not None and approval.status is ApprovalStatus.REQUESTED:
            approvals.append(approval)
    return approvals


# --------------------------------------------------------------------------- #
# P1-A — stale pending approvals are superseded
# --------------------------------------------------------------------------- #


def test_reprocessing_a_run_supersedes_its_pending_approval() -> None:
    repos, orchestrator = _setup()
    first = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert first.approval is not None
    run_id = first.run.run_id

    second = orchestrator.process_text(text=SHARMA_DISPATCH, run_id=run_id, now=NOW)

    assert second.approval is not None
    assert second.approval.approval_id != first.approval.approval_id
    assert second.superseded_approval_ids == [first.approval.approval_id]
    stale = repos.approvals.get_by_id(approval_id=first.approval.approval_id)
    assert stale is not None and stale.status is ApprovalStatus.SUPERSEDED
    assert stale.resolved_at is not None  # auditable terminal state, not deleted
    assert [a.approval_id for a in _requested_approvals(repos, run_id)] == [
        second.approval.approval_id
    ]

    with pytest.raises(ApprovalFlowError) as excinfo:
        _approve(orchestrator, first)
    assert excinfo.value.code == "APPROVAL_SUPERSEDED"
    assert _writes(repos) == (0, 0, 0)
    assert repos.tool_executions.list_by_run(run_id=run_id) == []

    executed = _approve(orchestrator, second)

    assert executed.run.status is VoiceRunStatus.COMPLETED
    order = repos.orders.list_all()[0]
    assert order.customer_id == CUST_SHARMA_BUILDERS_ID  # B's plan, not A's Kumar plan
    assert order.items[0].quantity == 200
    assert _writes(repos) == (1, 0, 1)
    assert not any(o.customer_id == CUST_KUMAR_CONSTRUCTIONS_ID for o in repos.orders.list_all())


def test_reprocessing_into_clarification_still_supersedes_pending_approval() -> None:
    repos, orchestrator = _setup()
    first = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert first.approval is not None

    clarified = orchestrator.process_text(
        text="Send 200 bags to Sharma.", run_id=first.run.run_id, now=NOW
    )

    assert clarified.decision is not None
    assert clarified.decision.decision is DecisionType.CLARIFY
    assert clarified.approval is None
    assert _requested_approvals(repos, first.run.run_id) == []
    with pytest.raises(ApprovalFlowError) as excinfo:
        _approve(orchestrator, first)
    assert excinfo.value.code == "APPROVAL_SUPERSEDED"
    assert _writes(repos) == (0, 0, 0)


def _fresh_api() -> AppContainer:
    return reset_container(clock=lambda: SYNTHETIC_BUSINESS_TIME)


def test_clarify_supersedes_old_approval_and_returns_the_new_approval_id() -> None:
    container = _fresh_api()
    user_headers = {"Authorization": f"Bearer {uuid4()}"}
    run_id = client.post("/runs", headers=user_headers).json()["run_id"]
    first = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_DISPATCH}, headers=user_headers
    ).json()
    assert first["approval_id"] is not None

    clarified = client.post(
        f"/runs/{run_id}/clarify",
        json={"clarification": SHARMA_DISPATCH},
        headers=user_headers,
    )

    assert clarified.status_code == 200
    body = clarified.json()
    assert body["decision"] == "APPROVAL_REQUIRED"
    assert body["approval_required"] is True
    assert body["approval_id"] is not None
    assert body["approval_id"] != first["approval_id"]
    assert body["superseded_approval_ids"] == [first["approval_id"]]
    assert body["planned_tools"] == ["create_order", "dispatch_order"]

    stale = client.post(f"/runs/{run_id}/approve", json={"approval_id": first["approval_id"]})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "APPROVAL_SUPERSEDED"
    assert _writes(container.repositories) == (0, 0, 0)

    current = client.post(f"/runs/{run_id}/approve", json={"approval_id": body["approval_id"]})
    assert current.status_code == 200
    assert current.json()["status"] == "COMPLETED"
    orders = container.repositories.orders.list_all()
    assert [o.customer_id for o in orders] == [CUST_SHARMA_BUILDERS_ID]
    assert _writes(container.repositories) == (1, 0, 1)


# --------------------------------------------------------------------------- #
# P1-B/C — temporal quote grounding
# --------------------------------------------------------------------------- #


def test_parso_resolves_to_the_quote_given_on_that_date() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=CANONICAL, now=NOW)

    assert result.run.status is VoiceRunStatus.APPROVAL_REQUIRED
    assert result.business_context is not None
    price = result.business_context.resolved_price
    assert price is not None
    assert price.source_quote_id == QUOTE_SHARMA_ULTRATECH_VALID_ID
    assert result.business_context.quotes[0].quote.quoted_on == date(2026, 10, 15)
    assert _writes(repos) == (0, 0, 0)


def test_parso_with_no_quote_on_that_date_clarifies_and_substitutes_nothing() -> None:
    """On 2026-11-09 "parso" is 2026-11-07; the only quote is from 2026-10-15."""
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text=CANONICAL, now=datetime(2026, 11, 9, 6, 30, tzinfo=NOW.tzinfo)
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.CLARIFY
    assert result.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert "2026-11-07" in result.message
    assert "not substituted" in result.message
    assert result.approval is None
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert result.business_context.quotes == []
    assert _writes(repos) == (0, 0, 0)
    assert repos.pending_executions.list_by_run(run_id=result.run.run_id) == []


def test_approval_later_keeps_parso_anchored_to_when_the_user_spoke() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=CANONICAL, now=NOW)

    # Approved the next day: "parso" must still mean 2026-10-15, not 2026-10-16.
    approved = _approve(orchestrator, processed, now=NOW + timedelta(days=1))

    assert approved.run.status is VoiceRunStatus.HANDOFF  # SEND_NOTIFICATION unsupported
    assert approved.executed_tools == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert _writes(repos) == (1, 1, 1)


def _resolver_inputs() -> tuple[
    ResolvedCustomer, ResolvedProduct, SemanticReference, SemanticPrice
]:
    repos = SyntheticRepositories()
    customer = repos.customers.get_by_id(customer_id=CUST_SHARMA_BUILDERS_ID)
    product = repos.products.get_by_id(product_id=PROD_ULTRATECH_CEMENT_ID)
    assert customer is not None and product is not None
    confidence = Confidence(score=0.9, source=ConfidenceSource.RULE)
    ref = SemanticReference(
        reference_id=uuid4(),
        reference_type=ReferenceType.HISTORICAL_PRICE,
        target_slot=SemanticSlot.PRICE,
        surface_text="rate wahi",
        normalized_text="rate wahi",
        span=TextSpan(start=0, end=9),
        confidence=confidence,
    )
    price = SemanticPrice(
        price_id=uuid4(),
        source=PriceSource.HISTORICAL_REFERENCE,
        reference_id=ref.reference_id,
        surface_text="rate wahi",
        span=TextSpan(start=0, end=9),
        confidence=confidence,
    )
    return (
        ResolvedCustomer(customer=customer, resolution_id=uuid4(), resolved_at=NOW),
        ResolvedProduct(product=product, resolution_id=uuid4(), resolved_at=NOW),
        ref,
        price,
    )


@pytest.mark.parametrize(
    ("anchor", "business_day", "expected_status", "selected"),
    [
        # quote valid on the requested date
        (date(2026, 10, 15), date(2026, 10, 17), ResolutionStatus.RESOLVED, True),
        # wrong-date quote is not selected
        (date(2026, 10, 16), date(2026, 10, 17), ResolutionStatus.NOT_FOUND, False),
        # matching date, but the validity window has passed (status still VALID)
        (date(2026, 10, 15), date(2026, 11, 16), ResolutionStatus.INVALID, False),
    ],
)
def test_quote_resolver_honours_date_and_validity_window(
    anchor: date, business_day: date, expected_status: ResolutionStatus, selected: bool
) -> None:
    customer, product, ref, price = _resolver_inputs()
    resolver = PriceQuoteResolver(SyntheticRepositories().quotes)

    result, _, resolved_price = resolver.resolve(
        customer=customer,
        product=product,
        pricing=[price],
        references=[ref],
        resolved_date=anchor,
        resolved_at=NOW,
        business_date=business_day,
        anchor_surface="parso",
    )

    assert result.status is expected_status
    assert (resolved_price is not None) is selected
    if selected:
        assert resolved_price is not None
        assert resolved_price.source_quote_id == QUOTE_SHARMA_ULTRATECH_VALID_ID


def test_quote_resolver_refuses_an_unresolvable_temporal_anchor() -> None:
    customer, product, ref, price = _resolver_inputs()
    resolver = PriceQuoteResolver(SyntheticRepositories().quotes)

    result, quote, resolved_price = resolver.resolve(
        customer=customer,
        product=product,
        pricing=[price],
        references=[ref],
        resolved_date=None,
        resolved_at=NOW,
        anchor_unresolved="parso",
    )

    assert result.status is ResolutionStatus.INVALID
    assert quote is None and resolved_price is None


def test_quote_past_valid_until_is_not_applied_even_if_status_is_valid() -> None:
    repos, orchestrator = _setup()
    quote = repos.quotes.get_by_id(quote_id=QUOTE_SHARMA_ULTRATECH_VALID_ID)
    assert quote is not None
    quote.valid_until = date(2026, 10, 16)  # status stays VALID; the window has passed

    result = orchestrator.process_text(text=CANONICAL, now=NOW)

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert result.validation_result is not None
    assert any(
        c.check_type == "QUOTE_VALIDITY" and c.status.value == "FAILED"
        for c in result.validation_result.checks
    )
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


def test_expired_status_quote_is_not_applied() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Send 50 bags of ACC cement to Sharma Builders at the old rate and dispatch.", now=NOW
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert _writes(repos) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# P1-E — spoken price is a claim; a valid quote is the authority
# --------------------------------------------------------------------------- #


def test_spoken_price_without_any_quote_is_never_executable() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Peenya Infra Works ko 20 bags UltraTech cement ₹1 per bag dispatch karo.", now=NOW
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.validation_result is not None
    assert any(
        c.check_type == "PRICE_AUTHORITY" and c.status.value == "FAILED"
        for c in result.validation_result.checks
    )
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert result.approval is None and result.plan is None
    assert _writes(repos) == (0, 0, 0)


def test_spoken_price_contradicting_the_quote_requires_confirmation() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Kumar Constructions ko 10 bags ACC cement ₹1 per bag dispatch karo.", now=NOW
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.CONFIRM
    assert result.business_context is not None
    price = result.business_context.resolved_price
    assert price is not None and price.unit_price == Decimal("400.00")  # the quote, not ₹1
    assert result.approval is None and result.plan is None
    assert _writes(repos) == (0, 0, 0)


def test_spoken_price_matching_a_current_quote_is_executable_at_the_quote_price() -> None:
    repos, orchestrator = _setup()

    processed = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹420 per bag dispatch karo.", now=NOW
    )

    assert processed.plan is not None
    item = processed.plan.tool_calls[0].arguments["items"][0]
    assert item["unit_price"] == "420.00"
    assert processed.business_context is not None
    assert processed.business_context.resolved_price is not None
    assert processed.business_context.resolved_price.source_quote_id == (
        QUOTE_SHARMA_ULTRATECH_VALID_ID
    )
    _approve(orchestrator, processed)
    assert repos.orders.list_all()[0].items[0].unit_price == Decimal("420.00")


def test_spoken_price_against_a_lapsed_quote_is_not_executable() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text=KUMAR_DISPATCH, now=datetime(2027, 1, 5, 6, 30, tzinfo=NOW.tzinfo)
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


def test_missing_price_is_not_executable() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement dispatch karo.", now=NOW
    )

    assert result.decision is not None
    assert result.decision.decision is DecisionType.BLOCKED
    assert result.approval is None and result.plan is None
    assert _writes(repos) == (0, 0, 0)


def test_planner_refuses_a_price_without_a_quote_source() -> None:
    _, orchestrator = _setup()
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert processed.business_context is not None and processed.understand_result is not None
    assert processed.business_context.resolved_price is not None
    assert processed.business_context.resolved_price.source_quote_id == QUOTE_KUMAR_ACC_VALID_ID
    unbacked = processed.business_context.model_copy(
        update={
            "resolved_price": processed.business_context.resolved_price.model_copy(
                update={"source_quote_id": None}
            )
        }
    )

    with pytest.raises(PlanningError):
        build_plan(
            run_id=processed.run.run_id,
            semantic_state=processed.understand_result.semantic_state,
            business_context=unbacked,
            tax_calculation=None,
        )


# --------------------------------------------------------------------------- #
# P1-F — UNKNOWN outcomes are resolved by read-back, never blindly retried
# --------------------------------------------------------------------------- #


def test_timeout_after_commit_is_reconciled_by_read_back_without_duplicate() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"create_order": "after_commit"}}
    )

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert _steps(result) == {
        "create_order": StepStatus.VERIFIED,
        "dispatch_order": StepStatus.VERIFIED,
    }
    assert result.step_outcomes[0].reconciled is True
    assert _writes(repos) == (1, 0, 1)  # exactly one order: no duplicate
    order_runs = [
        e
        for e in repos.tool_executions.list_by_run(run_id=result.run.run_id)
        if e.tool_name == "create_order"
    ]
    assert len(order_runs) == 1 and order_runs[0].attempt == 1
    assert order_runs[0].status is ToolExecutionStatus.SUCCEEDED


def test_timeout_before_commit_stays_unknown_and_hands_off_without_retry() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"create_order": "before_commit"}}
    )

    assert result.run.status is VoiceRunStatus.HANDOFF
    assert result.run.failure_code == "OUTCOME_UNKNOWN"
    assert result.handoff_case is not None
    assert _steps(result) == {
        "create_order": StepStatus.UNKNOWN,
        "dispatch_order": StepStatus.NOT_ATTEMPTED,
    }
    executions = repos.tool_executions.list_by_run(run_id=result.run.run_id)
    assert [(e.tool_name, e.status) for e in executions] == [
        ("create_order", ToolExecutionStatus.UNKNOWN)
    ]
    assert _writes(repos) == (0, 0, 0)
    assert "Executed" not in result.message
    assert _to_response(result).execution_success is False


def test_unknown_dispatch_after_commit_is_confirmed_not_repeated() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"dispatch_order": "after_commit"}}
    )

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert _writes(repos) == (1, 0, 1)
    assert result.step_outcomes[1].reconciled is True


def _execute_decision() -> Decision:
    return Decision(
        decision_id=uuid4(),
        run_id=uuid4(),
        decision=DecisionType.EXECUTE,
        reason_code=DecisionReasonCode.VALIDATED_LOW_RISK,
        reason="test",
        allowed=True,
        requires_approval=True,
        policy_version="1.0",
    )


def _approved() -> Approval:
    return Approval(
        approval_id=uuid4(),
        requested_by=uuid4(),
        approved_by=uuid4(),
        status=ApprovalStatus.APPROVED,
        snapshot_version="v1",
        requested_at=NOW,
        resolved_at=NOW,
    )


_ORDER_ARGS = {
    "customer_id": str(CUST_SHARMA_BUILDERS_ID),
    "currency": "INR",
    "items": [
        {
            "product_id": str(PROD_ULTRATECH_CEMENT_ID),
            "quantity": 10,
            "unit": "bag",
            "unit_price": "420.00",
            "line_total": "4200.00",
        }
    ],
}
_ORDER_EXPECTED = {
    "customer_id": str(CUST_SHARMA_BUILDERS_ID),
    "currency": "INR",
    "items_count": 1,
    "subtotal": "4200.00",
    "status": "DRAFT",
}


def _execute_order(
    service: ExecutionService, *, faults: dict[str, Any] | None = None, retry: bool = False
) -> Any:
    return service.execute(
        run_id=uuid4(),
        tool_name="create_order",
        arguments=_ORDER_ARGS,
        idempotency_key="unknown-key-1",
        decision=_execute_decision(),
        approval=_approved(),
        current_snapshot_version="v1",
        expected_state=_ORDER_EXPECTED,
        metadata={"simulate_timeout": faults or {}},
        retry_if_not_committed=retry,
        now=NOW,
    )


def test_repeat_call_on_unknown_reconciles_without_invoking_the_tool_again() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    first = _execute_order(service, faults={"create_order": "before_commit"})
    assert first.execution.status is ToolExecutionStatus.UNKNOWN

    again = _execute_order(service)  # no retry permission

    assert again.success is False
    assert again.execution.status is ToolExecutionStatus.UNKNOWN
    assert repos.orders.list_all() == []  # the tool was not invoked again


def test_explicit_retry_only_after_read_back_proves_nothing_was_committed() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    _execute_order(service, faults={"create_order": "before_commit"})

    retried = _execute_order(service, retry=True)

    assert retried.success is True
    assert retried.execution.attempt == 2
    assert len(repos.orders.list_all()) == 1


def test_explicit_retry_is_refused_when_the_write_was_committed() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)
    _execute_order(service, faults={"create_order": "after_commit"})  # reconciled at once
    assert len(repos.orders.list_all()) == 1

    again = _execute_order(service, retry=True)

    assert again.success is True
    assert len(repos.orders.list_all()) == 1  # no duplicate order


class _RaisingCreateOrder(CreateOrderTool):
    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raise TimeoutError("socket read timed out")


def test_write_tool_exception_is_unknown_not_failed() -> None:
    repos = SyntheticRepositories()
    registry = create_default_registry()
    registry.register(_RaisingCreateOrder())
    service = ExecutionService(repos, registry=registry)

    outcome = _execute_order(service)

    assert outcome.success is False
    assert outcome.execution.status is ToolExecutionStatus.UNKNOWN
    assert outcome.execution.error_code == "TOOL_EXCEPTION"


# --------------------------------------------------------------------------- #
# P1-G — partial execution is preserved per tool
# --------------------------------------------------------------------------- #


def test_dispatch_failure_after_order_and_invoice_is_partial_success() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=SHARMA_INVOICE_AND_DISPATCH, now=NOW)
    assert processed.plan is not None
    assert processed.plan.tool_names == ["create_order", "create_invoice_draft", "dispatch_order"]

    result = _approve(orchestrator, processed, faults={"simulate_dispatch_failure": True})

    assert result.run.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert _steps(result) == {
        "create_order": StepStatus.VERIFIED,
        "create_invoice_draft": StepStatus.VERIFIED,
        "dispatch_order": StepStatus.FAILED,
    }
    assert result.executed_tools == ["create_order", "create_invoice_draft"]
    assert _writes(repos) == (1, 1, 0)  # nothing rolled back, no dispatch claimed
    assert "Partially completed" in result.message
    assert "Failed: dispatch_order" in result.message
    response = _to_response(result)
    assert response.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert response.execution_success is False
    assert [(o.tool_name, o.status) for o in response.tool_outcomes] == [
        ("create_order", StepStatus.VERIFIED),
        ("create_invoice_draft", StepStatus.VERIFIED),
        ("dispatch_order", StepStatus.FAILED),
    ]


def test_invoice_failure_after_a_verified_order_is_partial() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka invoice banao.", now=NOW
    )
    assert processed.plan is not None
    assert processed.plan.tool_names == ["create_order", "create_invoice_draft"]

    result = _approve(orchestrator, processed, faults={"simulate_invoice_failure": True})

    # create_order succeeded, so this is partial; the invoice step failed definitively.
    assert result.run.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert _steps(result)["create_invoice_draft"] is StepStatus.FAILED
    assert _writes(repos) == (1, 0, 0)


class _RejectingCreateOrder(CreateOrderTool):
    """The business system definitively rejects the order; nothing is written."""

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            success=False, error_code="ORDER_REJECTED", error_message="Credit limit exceeded."
        )


def test_failure_of_the_first_step_is_failed_not_partial() -> None:
    registry = create_default_registry()
    registry.register(_RejectingCreateOrder())
    repos, orchestrator = _setup(registry)
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    result = _approve(orchestrator, processed)

    assert result.run.status is VoiceRunStatus.FAILED
    assert result.run.failure_code == "ORDER_REJECTED"
    assert _steps(result) == {
        "create_order": StepStatus.FAILED,
        "dispatch_order": StepStatus.NOT_ATTEMPTED,
    }
    assert result.executed_tools == []
    assert _writes(repos) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# P1-H — every write is verified by read-back of business state
# --------------------------------------------------------------------------- #


def test_happy_path_verifies_every_write_by_read_back() -> None:
    repos, orchestrator = _setup()
    processed = orchestrator.process_text(text=SHARMA_INVOICE_AND_DISPATCH, now=NOW)

    result = _approve(orchestrator, processed)

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert all(step.verification_status == "VERIFIED" for step in result.step_outcomes)
    verifications = repos.verifications.list_by_run(run_id=result.run.run_id)
    assert len(verifications) == 3
    assert {v.status for v in verifications} == {VerificationStatus.VERIFIED}
    assert _to_response(result).execution_success is True


class _AckWithoutWrite(Tool):
    """Claims success but never writes the order."""

    name = "create_order"
    purpose = "test double"
    side_effect = ToolSideEffect.REVERSIBLE_WRITE
    is_idempotent = True

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(success=True, data={"order_id": str(uuid4())})


class _WritesWrongSubtotal(CreateOrderTool):
    """Writes the order but with a subtotal other than the approved one."""

    def execute(self, *, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        result = super().execute(arguments=arguments, context=context)
        order = context.repositories.orders.get_by_id(order_id=UUID(result.data["order_id"]))
        assert isinstance(order, Order)
        context.repositories.orders.save(
            order=order.model_copy(update={"subtotal": order.subtotal + 1})
        )
        return result


@pytest.mark.parametrize(
    ("tool", "verification", "orders"),
    [
        (_AckWithoutWrite(), "UNVERIFIED", 0),
        (_WritesWrongSubtotal(), "MISMATCH", 1),
    ],
)
def test_acknowledged_write_that_does_not_verify_is_never_reported_done(
    tool: Tool, verification: str, orders: int
) -> None:
    registry = create_default_registry()
    registry.register(tool)
    repos, orchestrator = _setup(registry)
    processed = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    result = _approve(orchestrator, processed)

    assert result.run.status is VoiceRunStatus.HANDOFF
    assert result.step_outcomes[0].status is StepStatus.UNKNOWN
    assert result.step_outcomes[0].verification_status == verification
    assert result.step_outcomes[1].status is StepStatus.NOT_ATTEMPTED
    assert result.executed_tools == []
    assert _writes(repos) == (orders, 0, 0)  # no dispatch after an unverified order
    assert _to_response(result).execution_success is False


def test_write_without_expected_state_is_unverified() -> None:
    repos = SyntheticRepositories()
    service = ExecutionService(repos)

    outcome = service.execute(
        run_id=uuid4(),
        tool_name="create_order",
        arguments=_ORDER_ARGS,
        idempotency_key="no-expected-state",
        decision=_execute_decision(),
        approval=_approved(),
        current_snapshot_version="v1",
        now=NOW,
    )

    assert outcome.success is False
    assert outcome.verification is not None
    assert outcome.verification.status is VerificationStatus.UNVERIFIED
