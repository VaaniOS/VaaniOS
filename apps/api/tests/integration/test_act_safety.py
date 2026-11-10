"""
Phase A P0 regressions at orchestrator level.

Invariant: no business write executes unless it was explicitly requested,
semantically unambiguous, policy-approved, and bound to the actual approval
and plan of that run. Every test inspects the repositories directly.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.auth_support import STAFF
from vaaniflow.application.services.orchestrator import (
    ApprovalFlowError,
    VoiceWorkflowOrchestrator,
    WorkflowResult,
)
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.customer import Customer
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.semantic import RequestedActionType
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.execution.plan import build_plan
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)

# The synthetic dataset's business clock (2026-10-17 12:00 IST): "parso" is
# 2026-10-15, the date of the canonical Sharma Builders quote.
NOW = SYNTHETIC_BUSINESS_TIME

CANONICAL = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)
KUMAR_DISPATCH = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."


def _setup() -> tuple[SyntheticRepositories, VoiceWorkflowOrchestrator]:
    repos = SyntheticRepositories()
    return repos, VoiceWorkflowOrchestrator(repositories=repos)


def _writes(repos: SyntheticRepositories) -> tuple[int, int, int]:
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


def _approve(orchestrator: VoiceWorkflowOrchestrator, result: WorkflowResult) -> WorkflowResult:
    assert result.approval is not None
    return orchestrator.approve(
        actor=STAFF,
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        now=NOW,
    )


def _customer(repos: SyntheticRepositories, name: str) -> Customer:
    return next(c for c in repos.customers.list_all() if c.name == name)


# --------------------------------------------------------------------------- #
# P0-1 — actionability gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo.",
        "Sharma Builders ko 200 ya 300 bags UltraTech cement dispatch karo.",
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag dispatch karo, parso.",
        "Dispatch 200 bags UltraTech cement.",
    ],
)
def test_clarification_required_never_reaches_act(text: str) -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=text, now=NOW)

    assert result.understand_result is not None
    assert result.understand_result.actionability is Actionability.CLARIFICATION_REQUIRED
    assert result.decision is not None and result.decision.decision is DecisionType.CLARIFY
    assert result.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert result.business_context is None  # no business lookup happened
    assert result.approval is None and result.plan is None
    assert _writes(repos) == (0, 0, 0)


def test_clarification_preserves_reasons_and_ambiguities() -> None:
    _, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo.", now=NOW
    )

    assert result.understand_result is not None
    ambiguities = result.understand_result.semantic_state.ambiguities
    assert [a.candidates for a in ambiguities] == [["UltraTech cement", "ACC cement"]]
    assert ambiguities[0].description in result.message


def test_blocked_input_never_reaches_act() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text="Hello, how are you?", now=NOW)

    assert result.run.status is VoiceRunStatus.BLOCKED
    assert result.business_context is None and result.decision is None
    assert _writes(repos) == (0, 0, 0)


def test_partial_with_groundable_historical_rate_proceeds_to_approval() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=CANONICAL, now=NOW)

    assert result.understand_result is not None
    assert result.understand_result.actionability is Actionability.PARTIAL
    assert result.run.status is VoiceRunStatus.APPROVAL_REQUIRED
    assert result.business_context is not None
    assert result.business_context.resolved_price is not None
    assert result.business_context.resolved_price.source_quote_id is not None
    assert _writes(repos) == (0, 0, 0)


def test_partial_with_unresolvable_context_reference_clarifies() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹400 per bag dispatch karo, that order.",
        now=NOW,
    )

    assert result.understand_result is not None
    assert result.understand_result.actionability is Actionability.PARTIAL
    assert result.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert "'that order' (ORDER)" in result.message
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# P0-2 — negated actions never execute
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch mat karo.",
        "Don't dispatch 20 bags of UltraTech cement to Sharma Builders at ₹400 per bag.",
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch karo, invoice mat banao.",
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag ka invoice banao, dispatch mat karo.",
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch karo. Dispatch mat karo.",
    ],
)
def test_request_with_negated_action_never_executes(text: str) -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=text, now=NOW)

    assert result.understand_result is not None
    assert result.understand_result.semantic_state.negated_actions
    assert result.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert result.approval is None  # nothing could ever be approved
    assert repos.pending_executions.list_by_run(run_id=result.run.run_id) == []
    assert _writes(repos) == (0, 0, 0)


def test_planner_never_plans_a_tool_for_a_negated_action() -> None:
    """Defence in depth: even if a negated request reached planning."""
    _, orchestrator = _setup()
    transcript = Transcript(
        transcript_id=uuid4(),
        provider="test",
        text="Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch karo, "
        "invoice mat banao.",
        created_at=NOW,
    )
    state = orchestrator.compiler.compile(transcript)
    context = orchestrator.context_resolver.resolve(
        semantic_state=state, run_id=uuid4(), run_timestamp=NOW
    )

    plan = build_plan(
        run_id=uuid4(),
        semantic_state=state,
        business_context=context.business_context,
        tax_calculation=context.tax_calculation,
    )

    assert plan.excluded_negated_actions == [RequestedActionType.CREATE_INVOICE_DRAFT]
    assert plan.tool_names == ["create_order", "dispatch_order"]


def test_policy_never_executes_when_an_action_is_negated() -> None:
    _, orchestrator = _setup()
    transcript = Transcript(
        transcript_id=uuid4(),
        provider="test",
        text="Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch mat karo.",
        created_at=NOW,
    )
    state = orchestrator.compiler.compile(transcript)
    context = orchestrator.context_resolver.resolve(
        semantic_state=state, run_id=uuid4(), run_timestamp=NOW
    )
    validation = orchestrator.validation_engine.validate(
        semantic_state=state,
        business_context=context.business_context,
        tax_calculation=context.tax_calculation,
        run_id=uuid4(),
    )
    risk = orchestrator.risk_assessor.assess(
        semantic_state=state,
        business_context=context.business_context,
        validation_result=validation,
        run_id=uuid4(),
    )

    decision = orchestrator.policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=state,
        business_context=context.business_context,
        is_approved=True,
        run_id=uuid4(),
    )

    assert decision.decision is DecisionType.CLARIFY
    assert decision.allowed is False


# --------------------------------------------------------------------------- #
# P0-3 — the tool plan comes from requested actions
# --------------------------------------------------------------------------- #


def test_check_price_is_read_only() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka rate kya hai?", now=NOW
    )

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert result.plan is not None and result.plan.tool_names == []
    assert result.plan.read_actions == [RequestedActionType.CHECK_PRICE]
    # Answered from the quote record, not echoed from the spoken claim.
    assert "Price: 420.00 INR/bag" in result.message
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


def test_check_inventory_is_read_only() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹420 per bag ka stock kitna hai?",
        now=NOW,
    )

    assert result.run.status is VoiceRunStatus.COMPLETED
    assert result.plan is not None and result.plan.tool_names == []
    assert "Stock CEM-UT-001: 450 sellable" in result.message
    assert _writes(repos) == (0, 0, 0)


def test_dispatch_only_never_creates_an_invoice() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert result.plan is not None and result.plan.tool_names == ["create_order", "dispatch_order"]

    executed = _approve(orchestrator, result)

    assert executed.run.status is VoiceRunStatus.COMPLETED
    assert executed.executed_tools == ["create_order", "dispatch_order"]
    assert _writes(repos) == (1, 0, 1)


def test_invoice_only_never_dispatches() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Kumar Constructions ko 10 bags ACC cement ₹400 per bag ka invoice banao.", now=NOW
    )
    assert result.plan is not None
    assert result.plan.tool_names == ["create_order", "create_invoice_draft"]

    executed = _approve(orchestrator, result)

    assert executed.run.status is VoiceRunStatus.COMPLETED
    assert _writes(repos) == (1, 1, 0)
    assert repos.invoices.list_all()[0].status.value == "DRAFT"  # drafted, never issued


def test_unsupported_requested_action_is_not_silently_dropped() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Sharma Builders ko 20 bags UltraTech cement ₹420 per bag WhatsApp pe message karo.",
        now=NOW,
    )

    assert result.run.status is VoiceRunStatus.HANDOFF
    assert result.plan is not None
    assert result.plan.unsupported_actions == [RequestedActionType.SEND_NOTIFICATION]
    assert result.handoff_case is not None
    assert result.handoff_case.blocked_actions == ["SEND_NOTIFICATION"]
    assert "SEND_NOTIFICATION" in result.message
    assert _writes(repos) == (0, 0, 0)


def test_canonical_hinglish_plan_reflects_requested_actions() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=CANONICAL, now=NOW)

    assert result.plan is not None
    assert result.plan.executable_actions == [
        RequestedActionType.DISPATCH,
        RequestedActionType.CREATE_INVOICE_DRAFT,
        RequestedActionType.SEND_NOTIFICATION,
        RequestedActionType.REQUEST_APPROVAL,
    ]
    assert result.plan.tool_names == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert result.plan.unsupported_actions == [RequestedActionType.SEND_NOTIFICATION]
    assert result.approval is not None
    assert result.approval.status is ApprovalStatus.REQUESTED
    assert _writes(repos) == (0, 0, 0)

    executed = _approve(orchestrator, result)

    # issue_invoice was never requested, so it never runs; the notification is
    # unsupported, so the run is handed off instead of reported COMPLETED.
    assert executed.executed_tools == ["create_order", "create_invoice_draft", "dispatch_order"]
    assert executed.run.status is VoiceRunStatus.HANDOFF
    assert executed.handoff_case is not None
    assert executed.handoff_case.blocked_actions == ["SEND_NOTIFICATION"]
    order = repos.orders.list_all()[0]
    assert (order.items[0].quantity, order.items[0].unit_price) == (200, Decimal("420.00"))
    assert repos.invoices.list_all()[0].status.value == "DRAFT"
    sharma = _customer(repos, "Sharma Builders")
    assert repos.dispatches.list_all()[0].delivery_address == sharma.address


# --------------------------------------------------------------------------- #
# P0-4 / P0-5 — approval bound to run, plan and snapshot
# --------------------------------------------------------------------------- #


def test_approve_executes_the_stored_plan_of_that_run() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    _approve(orchestrator, result)

    kumar = _customer(repos, "Kumar Constructions")
    order = repos.orders.list_all()[0]
    product = repos.products.get_by_id(product_id=order.items[0].product_id)
    assert order.customer_id == kumar.customer_id
    assert product is not None and product.sku == "CEM-ACC-001"
    assert (order.items[0].quantity, order.items[0].unit_price) == (10, Decimal(400))


def test_approval_of_run_a_cannot_execute_run_b() -> None:
    repos, orchestrator = _setup()
    run_a = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    run_b = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert run_a.approval is not None

    with pytest.raises(ApprovalFlowError) as error:
        orchestrator.approve(
            actor=STAFF,
            run_id=run_b.run.run_id,
            approval_id=run_a.approval.approval_id,
            now=NOW,
        )

    assert error.value.code == "APPROVAL_RUN_MISMATCH"
    assert _writes(repos) == (0, 0, 0)


def test_unknown_approval_id_cannot_execute() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    with pytest.raises(ApprovalFlowError) as error:
        orchestrator.approve(actor=STAFF, run_id=result.run.run_id, approval_id=uuid4(), now=NOW)

    assert error.value.code == "APPROVAL_NOT_FOUND"
    assert _writes(repos) == (0, 0, 0)


def test_rejected_approval_can_never_execute() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert result.approval is not None

    rejected = orchestrator.reject(
        actor=STAFF,
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        now=NOW,
    )
    assert rejected.run.status is VoiceRunStatus.BLOCKED
    assert rejected.approval is not None and rejected.approval.status is ApprovalStatus.REJECTED

    with pytest.raises(ApprovalFlowError) as error:
        _approve(orchestrator, result)

    assert error.value.code == "APPROVAL_NOT_PENDING"
    assert _writes(repos) == (0, 0, 0)


def test_an_approval_executes_at_most_once() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    _approve(orchestrator, result)

    with pytest.raises(ApprovalFlowError) as error:
        _approve(orchestrator, result)

    assert error.value.code == "APPROVAL_NOT_PENDING"
    assert _writes(repos) == (1, 0, 1)


def test_plan_change_after_request_expires_the_approval() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    _customer(repos, "Kumar Constructions").address = "New Site, Hosur Road"

    executed = _approve(orchestrator, result)

    assert executed.run.status is VoiceRunStatus.FAILED
    assert executed.run.failure_code == "APPROVAL_EXPIRED"
    assert executed.approval is not None and executed.approval.status is ApprovalStatus.EXPIRED
    assert _writes(repos) == (0, 0, 0)


def test_business_state_change_after_request_expires_the_approval() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    for record in repos.inventory.list_all():
        record.reserved_quantity += 1

    executed = _approve(orchestrator, result)

    assert executed.run.failure_code == "APPROVAL_EXPIRED"
    assert "business state changed" in executed.message
    assert _writes(repos) == (0, 0, 0)


def test_unchanged_business_state_keeps_the_approval_valid_over_time() -> None:
    repos, orchestrator = _setup()
    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)
    assert result.approval is not None

    executed = orchestrator.approve(
        actor=STAFF,
        run_id=result.run.run_id,
        approval_id=result.approval.approval_id,
        now=NOW + timedelta(hours=1),
    )

    assert executed.run.status is VoiceRunStatus.COMPLETED
    assert _writes(repos) == (1, 0, 1)


# --------------------------------------------------------------------------- #
# P0-6 — multi-item is never truncated
# --------------------------------------------------------------------------- #


def test_multi_item_request_never_executes_a_subset() -> None:
    repos, orchestrator = _setup()

    result = orchestrator.process_text(
        text="Send 20 bags of UltraTech cement at ₹400 per bag and 10 kg of steel rods at "
        "₹60 per kg to Sharma Builders and dispatch.",
        now=NOW,
    )

    assert result.understand_result is not None
    assert len(result.understand_result.semantic_state.items) == 2
    assert result.run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    assert result.run.status is not VoiceRunStatus.COMPLETED
    assert "2 line items" in result.message
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# Hard-coded facts removed
# --------------------------------------------------------------------------- #


def test_dispatch_uses_the_customer_address_on_record() -> None:
    repos, orchestrator = _setup()

    _approve(orchestrator, orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW))

    kumar = _customer(repos, "Kumar Constructions")
    dispatch = repos.dispatches.list_all()[0]
    assert dispatch.delivery_address == kumar.address
    assert dispatch.delivery_address != "Site 12, Peenya"


def test_missing_delivery_address_fails_safely() -> None:
    repos, orchestrator = _setup()
    _customer(repos, "Kumar Constructions").address = None

    result = orchestrator.process_text(text=KUMAR_DISPATCH, now=NOW)

    assert result.run.status is VoiceRunStatus.BLOCKED
    assert result.run.failure_code == "MISSING_BUSINESS_FACT"
    assert "no delivery address" in result.message
    assert result.approval is None
    assert _writes(repos) == (0, 0, 0)


def test_missing_tax_rule_fails_safely_for_an_invoice() -> None:
    repos, orchestrator = _setup()
    repos.tax_rules = type(repos.tax_rules)([])
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)

    result = orchestrator.process_text(
        text="Kumar Constructions ko 10 bags ACC cement ₹400 per bag ka invoice banao.", now=NOW
    )

    assert result.run.status is VoiceRunStatus.BLOCKED
    assert "Tax could not be calculated" in result.message
    assert _writes(repos) == (0, 0, 0)
