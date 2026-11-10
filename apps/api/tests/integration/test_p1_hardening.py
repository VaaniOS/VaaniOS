"""
Phase B hardening regressions.

Deterministic business clock, temporal quote matching, quote validity
windows, UNKNOWN in the middle of a plan, the canonical request end to end
over HTTP, and preservation of UNKNOWN history after reconciliation.
Execution tests inspect repository state, not only returned statuses.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.auth_support import STAFF, auth, provider
from vaaniflow.api.app import app
from vaaniflow.api.dependencies import (
    BUSINESS_CLOCK_ENV,
    AppContainer,
    business_clock_from_env,
    reset_container,
)
from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator, WorkflowResult
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.invoice import InvoiceStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.domain.schemas.semantic import (
    PriceSource,
    ReferenceType,
    RequestedActionType,
    TaxTreatment,
)
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.evaluation.scenarios import list_all_scenarios
from vaaniflow.execution.plan import StepStatus
from vaaniflow.execution.service import ExecutionService
from vaaniflow.infrastructure.repositories.memory import InMemoryQuoteRepository
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    PROD_ULTRATECH_CEMENT_ID,
    QUOTE_SHARMA_ULTRATECH_VALID_ID,
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)

T1 = SYNTHETIC_BUSINESS_TIME  # 2026-10-17 12:00 IST
D = date(2026, 10, 15)  # what "parso" means when spoken at T1

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)
SPOKEN_420 = "Sharma Builders ko 20 bags UltraTech cement ₹420 per bag dispatch karo."
INVOICE_AND_DISPATCH = (
    "Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka invoice banao aur dispatch karo."
)

client = TestClient(app)


def _quote(quoted_on: date, price: str, valid_until: date | None) -> Quote:
    return Quote(
        quote_id=uuid4(),
        customer_id=CUST_SHARMA_BUILDERS_ID,
        product_id=PROD_ULTRATECH_CEMENT_ID,
        unit="bag",
        unit_price=Decimal(price),
        currency="INR",
        quoted_on=quoted_on,
        valid_until=valid_until,
        status=QuoteStatus.VALID,
        created_at=T1,
        updated_at=T1,
    )


def _with_quotes(quotes: list[Quote]) -> tuple[SyntheticRepositories, VoiceWorkflowOrchestrator]:
    """Synthetic business data whose only Sharma/UltraTech quotes are ``quotes``."""
    repos = SyntheticRepositories()
    repos.quotes = InMemoryQuoteRepository(quotes)
    return repos, VoiceWorkflowOrchestrator(repositories=repos)


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
    now: datetime = T1,
    faults: dict[str, Any] | None = None,
) -> WorkflowResult:
    assert result.approval is not None
    return orchestrator.approve(
        actor=STAFF,
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        simulated_faults=faults,
        now=now,
    )


def _assert_nothing_planned(repos: SyntheticRepositories, result: WorkflowResult) -> None:
    assert result.business_context is not None
    assert result.business_context.resolved_price is None
    assert result.approval is None and result.plan is None
    assert repos.pending_executions.list_by_run(run_id=result.run.run_id) == []
    assert repos.tool_executions.list_by_run(run_id=result.run.run_id) == []
    assert _writes(repos) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# 1. Business clock: real by default, fixed only when explicit
# --------------------------------------------------------------------------- #


def test_production_default_clock_is_the_real_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BUSINESS_CLOCK_ENV, raising=False)

    container = AppContainer()
    before = datetime.now(UTC)
    observed = container.orchestrator.clock()
    after = datetime.now(UTC)

    assert container.business_clock_source == "real"
    assert before <= observed <= after
    assert VoiceWorkflowOrchestrator(repositories=SyntheticRepositories()).clock() >= before


def test_demo_clock_is_explicit_and_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BUSINESS_CLOCK_ENV, "synthetic")

    container = AppContainer()

    assert container.business_clock_source == f"fixed:{SYNTHETIC_BUSINESS_TIME.isoformat()}"
    assert container.orchestrator.clock() == SYNTHETIC_BUSINESS_TIME
    clock, _ = business_clock_from_env({BUSINESS_CLOCK_ENV: "2026-10-20T10:00:00+05:30"})
    assert clock is not None and clock() == datetime(2026, 10, 20, 4, 30, tzinfo=UTC)


@pytest.mark.parametrize("value", ["yesterday", "2026-10-17T12:00:00"])
def test_invalid_demo_clock_fails_instead_of_falling_back(value: str) -> None:
    with pytest.raises(ValueError):
        business_clock_from_env({BUSINESS_CLOCK_ENV: value})


def test_evaluation_clock_does_not_leak_into_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BUSINESS_CLOCK_ENV, raising=False)
    container = AppContainer()

    suite = container.runner.run_all()
    observed = container.orchestrator.clock()

    assert suite.evaluation_timestamp == SYNTHETIC_BUSINESS_TIME
    assert container.business_clock_source == "real"
    assert abs(observed - datetime.now(UTC)) < timedelta(minutes=1)


def test_same_request_under_the_synthetic_clock_is_deterministic() -> None:
    outcomes = []
    for _ in range(2):
        repos = SyntheticRepositories()
        orchestrator = VoiceWorkflowOrchestrator(
            repositories=repos, clock=lambda: SYNTHETIC_BUSINESS_TIME
        )
        result = orchestrator.process_text(text=CANONICAL)
        assert result.plan is not None
        outcomes.append((result.plan.fingerprint, result.plan.snapshot_version))
    assert outcomes[0] == outcomes[1]

    scenario = list_all_scenarios()[0]
    first = EvaluationRunner().run_scenario(scenario)
    second = EvaluationRunner().run_scenario(scenario)
    assert (first.actual_decision, first.actual_status) == (
        second.actual_decision,
        second.actual_status,
    )


# --------------------------------------------------------------------------- #
# 2. Temporal quote matching: "parso" = D; no other date is substituted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "quotes"),
    [
        ("only D-1", [_quote(D - timedelta(days=1), "410", date(2026, 12, 31))]),
        ("only D+1", [_quote(D + timedelta(days=1), "430", date(2026, 12, 31))]),
        (
            "D-1 and D+1",
            [
                _quote(D - timedelta(days=1), "410", date(2026, 12, 31)),
                _quote(D + timedelta(days=1), "430", date(2026, 12, 31)),
            ],
        ),
        ("only D-25", [_quote(D - timedelta(days=25), "400", date(2026, 12, 31))]),
        ("only a current quote", [_quote(T1.date(), "420", date(2026, 12, 31))]),
    ],
)
def test_referenced_date_without_a_quote_clarifies_and_selects_nothing(
    label: str, quotes: list[Quote]
) -> None:
    repos, orchestrator = _with_quotes(quotes)

    result = orchestrator.process_text(text=CANONICAL, now=T1)

    assert result.decision is not None, label
    assert result.decision.decision is DecisionType.CLARIFY, label
    assert f"given on {D.isoformat()}" in result.message
    assert "not substituted" in result.message
    assert result.business_context is not None
    assert result.business_context.quotes == []
    _assert_nothing_planned(repos, result)


def test_two_valid_quotes_on_the_referenced_date_clarify_without_ranking() -> None:
    repos, orchestrator = _with_quotes(
        [_quote(D, "420", date(2026, 11, 15)), _quote(D, "425", date(2026, 11, 15))]
    )

    result = orchestrator.process_text(text=CANONICAL, now=T1)

    assert result.decision is not None
    assert result.decision.decision is DecisionType.CLARIFY
    assert "Ambiguous quote" in result.message
    _assert_nothing_planned(repos, result)


def test_quote_dated_in_the_future_is_not_used() -> None:
    repos, orchestrator = _with_quotes([_quote(T1.date() + timedelta(days=1), "420", None)])

    result = orchestrator.process_text(text=SPOKEN_420, now=T1)

    assert result.decision is not None
    assert result.decision.decision is DecisionType.HUMAN_HANDOFF
    _assert_nothing_planned(repos, result)


def test_later_approval_keeps_the_reference_date_of_the_utterance() -> None:
    """Processed at T1 ("parso" = 10-15), approved on 10-18 (where "parso" would be 10-16)."""
    q_spoken_date = _quote(D, "420", date(2026, 11, 15))
    q_approval_date = _quote(D + timedelta(days=1), "425", date(2026, 11, 15))
    repos, orchestrator = _with_quotes([q_spoken_date, q_approval_date])
    processed = orchestrator.process_text(text=CANONICAL, now=T1)
    assert processed.business_context is not None
    assert processed.business_context.quotes[0].quote.quote_id == q_spoken_date.quote_id

    approved = _approve(orchestrator, processed, now=T1 + timedelta(days=1))

    assert approved.executed_tools == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert approved.business_context is not None
    assert approved.business_context.quotes[0].quote.quote_id == q_spoken_date.quote_id
    order = repos.orders.list_all()[0]
    assert order.items[0].unit_price == Decimal(420)  # not the 10-16 quote's 425
    assert _writes(repos) == (1, 1, 1)


# --------------------------------------------------------------------------- #
# 3. Quote validity: quoted_on <= business date <= valid_until (inclusive)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "valid_until", "usable"),
    [
        ("inside window", date(2026, 11, 15), True),
        ("boundary: valid_until == business date", T1.date(), True),
        ("open-ended", None, True),
        ("expired: valid_until < business date", T1.date() - timedelta(days=1), False),
    ],
)
def test_quote_validity_window_on_the_business_date(
    label: str, valid_until: date | None, usable: bool
) -> None:
    quote = _quote(D, "420", valid_until)
    repos, orchestrator = _with_quotes([quote])

    result = orchestrator.process_text(text=CANONICAL, now=T1)

    assert result.decision is not None, label
    if usable:
        assert result.decision.decision is DecisionType.APPROVAL_REQUIRED, label
        assert result.business_context is not None
        assert result.business_context.resolved_price is not None
        assert result.business_context.resolved_price.source_quote_id == quote.quote_id
        approved = _approve(orchestrator, result)
        assert repos.orders.list_all()[0].items[0].unit_price == Decimal(420)
        assert approved.executed_tools == ["create_order", "create_invoice_draft", "dispatch_order"]
    else:
        assert result.decision.decision is DecisionType.HUMAN_HANDOFF, label
        _assert_nothing_planned(repos, result)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 14), False),  # before quoted_on: not yet valid
        (date(2026, 10, 15), True),  # quoted_on is the start boundary
        (date(2026, 11, 15), True),  # valid_until is inclusive
        (date(2026, 11, 16), False),  # after valid_until
    ],
)
def test_quote_applicability_boundaries(day: date, expected: bool) -> None:
    assert _quote(D, "420", date(2026, 11, 15)).is_applicable_on(day) is expected


# --------------------------------------------------------------------------- #
# 4. UNKNOWN in the middle of a plan
# --------------------------------------------------------------------------- #


def test_unknown_invoice_mid_plan_stops_before_dispatch_and_hands_off() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)
    processed = orchestrator.process_text(text=INVOICE_AND_DISPATCH, now=T1)
    assert processed.plan is not None
    assert processed.plan.tool_names == ["create_order", "create_invoice_draft", "dispatch_order"]

    result = _approve(
        orchestrator,
        processed,
        faults={"simulate_timeout": {"create_invoice_draft": "before_commit"}},
    )

    assert [(s.tool_name, s.status) for s in result.step_outcomes] == [
        ("create_order", StepStatus.VERIFIED),
        ("create_invoice_draft", StepStatus.UNKNOWN),
        ("dispatch_order", StepStatus.NOT_ATTEMPTED),
    ]
    assert result.run.status is VoiceRunStatus.HANDOFF
    assert result.run.failure_code == "OUTCOME_UNKNOWN"
    assert _writes(repos) == (1, 0, 0)
    executions = repos.tool_executions.list_by_run(run_id=result.run.run_id)
    assert [(e.tool_name, e.status) for e in executions] == [
        ("create_order", ToolExecutionStatus.SUCCEEDED),
        ("create_invoice_draft", ToolExecutionStatus.UNKNOWN),
    ]  # dispatch_order was never attempted
    verifications = repos.verifications.list_by_run(run_id=result.run.run_id)
    assert [v.status for v in verifications] == [VerificationStatus.VERIFIED]
    handoffs = repos.handoffs.list_by_run(run_id=result.run.run_id)
    assert len(handoffs) == 1 and "create_invoice_draft" in handoffs[0].reason
    assert result.executed_tools == ["create_order"]


# --------------------------------------------------------------------------- #
# 5. Canonical request over HTTP under the explicit demo clock
# --------------------------------------------------------------------------- #


@pytest.fixture
def demo_container(monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContainer]:
    """API container on the explicit demo clock; restored to the real clock afterwards."""
    monkeypatch.setenv(BUSINESS_CLOCK_ENV, "synthetic")
    yield reset_container(identity_provider=provider())
    monkeypatch.delenv(BUSINESS_CLOCK_ENV)
    assert reset_container(identity_provider=provider()).business_clock_source == "real"


def test_canonical_request_over_http_end_to_end(demo_container: AppContainer) -> None:
    container = demo_container
    repos = container.repositories
    assert container.business_clock_source.startswith("fixed:")

    run_id = client.post("/runs", headers=auth()).json()["run_id"]
    processed = client.post(f"/runs/{run_id}/process", json={"text": CANONICAL}, headers=auth())
    assert processed.status_code == 200
    body = processed.json()

    # Approval required; nothing written yet.
    assert body["decision"] == "APPROVAL_REQUIRED"
    assert body["approval_required"] is True
    assert body["actionability"] == "PARTIAL"
    assert body["planned_tools"] == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert body["unsupported_actions"] == ["SEND_NOTIFICATION"]
    assert _writes(repos) == (0, 0, 0)

    # The approval is bound to this run and to the persisted plan.
    approval_id = UUID(body["approval_id"])
    approval = repos.approvals.get_by_id(approval_id=approval_id)
    pending = repos.pending_executions.get_by_approval_id(approval_id=approval_id)
    assert approval is not None and pending is not None
    assert approval.status is ApprovalStatus.REQUESTED
    assert str(pending.plan.run_id) == run_id
    assert approval.snapshot_version == pending.plan.snapshot_version == body["snapshot_version"]

    # Semantic state as persisted for execution.
    state = pending.understand_result.semantic_state
    assert state.customer is not None and state.customer.surface_text == "Sharma Builders"
    assert len(state.items) == 1
    assert state.items[0].product.surface_text == "Ultratech cement"
    assert state.items[0].quantity is not None
    assert state.items[0].quantity.value == 200 and state.items[0].quantity.unit == "bag"
    assert state.tax is not None and state.tax.treatment is TaxTreatment.EXCLUSIVE
    price = state.pricing[0]
    assert price.source is PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE
    assert price.amount == 420
    reference = next(r for r in state.references if r.reference_id == price.reference_id)
    assert reference.reference_type is ReferenceType.HISTORICAL_PRICE
    parso = next(
        e for e in state.temporal_expressions if e.expression_id == reference.temporal_expression_id
    )
    assert parso.surface_text == "parso" and parso.day_offset == -2
    assert {a.action_type for a in state.requested_actions} >= {
        RequestedActionType.DISPATCH,
        RequestedActionType.CREATE_INVOICE_DRAFT,
    }

    # The plan was built from exactly the 2026-10-15 quote: re-resolving the
    # persisted state at the same clock reproduces the approval's snapshot.
    context = container.orchestrator.context_resolver.resolve(
        semantic_state=state,
        run_id=pending.plan.run_id,
        run_timestamp=SYNTHETIC_BUSINESS_TIME,
        utterance_timestamp=pending.understand_result.transcript.created_at,
    )
    assert [q.quote.quote_id for q in context.business_context.quotes] == [
        QUOTE_SHARMA_ULTRATECH_VALID_ID
    ]
    assert context.business_context.quotes[0].quote.quoted_on == D
    assert context.business_context.resolved_price is not None
    assert context.business_context.resolved_price.source_quote_id == (
        QUOTE_SHARMA_ULTRATECH_VALID_ID
    )
    tax = context.tax_calculation
    assert tax is not None
    item = pending.plan.tool_calls[0].arguments["items"][0]
    assert item["unit_price"] == "420.00" and item["quantity"] == 200

    # Owner approves exactly that approval.
    approved = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": str(approval_id)}, headers=auth()
    )
    assert approved.status_code == 200
    result = approved.json()
    assert result["status"] == "HANDOFF"  # SEND_NOTIFICATION is unsupported, handed off
    assert result["executed_tools"] == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert [o["status"] for o in result["tool_outcomes"]] == ["VERIFIED"] * 3
    assert result["execution_success"] is True

    # Actual repository state.
    assert _writes(repos) == (1, 1, 1)
    customer = repos.customers.get_by_id(customer_id=CUST_SHARMA_BUILDERS_ID)
    assert customer is not None
    order = repos.orders.list_all()[0]
    assert order.customer_id == CUST_SHARMA_BUILDERS_ID
    assert order.items[0].product_id == PROD_ULTRATECH_CEMENT_ID
    assert order.items[0].quantity == 200 and order.items[0].unit == "bag"
    assert order.items[0].unit_price == Decimal("420.00")
    assert order.subtotal == Decimal("84000.00") == tax.taxable_amount
    assert order.delivery_address == customer.address

    invoice = repos.invoices.list_all()[0]
    assert invoice.order_id == order.order_id
    assert invoice.status is InvoiceStatus.DRAFT  # a draft, never issued
    assert invoice.subtotal == tax.taxable_amount
    assert invoice.tax_total == tax.total_tax > 0  # rule-computed, GST exclusive
    assert invoice.total == tax.total_amount == invoice.subtotal + invoice.tax_total

    dispatch = repos.dispatches.list_all()[0]
    assert dispatch.order_id == order.order_id
    assert dispatch.status.value == "DISPATCHED"
    assert dispatch.delivery_address == customer.address

    verifications = repos.verifications.list_by_run(run_id=UUID(run_id))
    assert [v.status for v in verifications] == [VerificationStatus.VERIFIED] * 3
    executions = repos.tool_executions.list_by_run(run_id=UUID(run_id))
    assert [e.tool_name for e in executions] == [
        "create_order",
        "create_invoice_draft",
        "dispatch_order",
    ]  # issue_invoice and notification never executed
    final = repos.approvals.get_by_id(approval_id=approval_id)
    assert final is not None and final.status is ApprovalStatus.APPROVED
    handoffs = repos.handoffs.list_by_run(run_id=UUID(run_id))
    assert len(handoffs) == 1 and "SEND_NOTIFICATION" in handoffs[0].reason


# --------------------------------------------------------------------------- #
# 6. Reconciliation keeps the record that the outcome was once UNKNOWN
# --------------------------------------------------------------------------- #


def test_reconciled_execution_keeps_its_unknown_history() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)
    processed = orchestrator.process_text(text=SPOKEN_420, now=T1)

    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"create_order": "after_commit"}}
    )

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert _writes(repos) == (1, 0, 1)  # one order: no duplicate
    order_executions = [
        e
        for e in repos.tool_executions.list_by_run(run_id=result.run.run_id)
        if e.tool_name == "create_order"
    ]
    assert len(order_executions) == 1  # same record, not a second execution
    execution = order_executions[0]
    assert execution.status is ToolExecutionStatus.SUCCEEDED
    assert execution.reconciled is True
    assert execution.prior_status is ToolExecutionStatus.UNKNOWN
    assert execution.prior_error_code == "TOOL_TIMEOUT"
    assert execution.prior_error_message
    assert execution.attempt == 1
    trace = orchestrator.trace_service.get_run_trace(run_id=result.run.run_id)
    assert trace is not None
    assert any(
        "reconciled by read-back after UNKNOWN (TOOL_TIMEOUT)" in (e.output_summary or "")
        for e in trace.events
    )


def test_explicit_retry_keeps_the_unknown_it_replaced() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)
    processed = orchestrator.process_text(text=SPOKEN_420, now=T1)
    result = _approve(
        orchestrator, processed, faults={"simulate_timeout": {"create_order": "before_commit"}}
    )
    unknown = repos.tool_executions.list_by_run(run_id=result.run.run_id)[0]
    assert unknown.status is ToolExecutionStatus.UNKNOWN
    assert result.approval is not None and result.decision is not None

    retried = ExecutionService(repos).execute(
        run_id=unknown.run_id,
        tool_name=unknown.tool_name,
        arguments=unknown.arguments,
        idempotency_key=unknown.idempotency_key,
        decision=result.decision,
        approval=result.approval,
        expected_state={"customer_id": str(CUST_SHARMA_BUILDERS_ID), "status": "DRAFT"},
        retry_if_not_committed=True,
        now=T1,
    )

    assert retried.success is True
    assert len(repos.orders.list_all()) == 1
    record = repos.tool_executions.get_by_id(execution_id=unknown.execution_id)
    assert record is not None
    assert record.status is ToolExecutionStatus.SUCCEEDED and record.attempt == 2
    assert record.reconciled is False  # retried after proof nothing was committed
    assert record.prior_status is ToolExecutionStatus.UNKNOWN
    assert record.prior_error_code == "TOOL_TIMEOUT"
