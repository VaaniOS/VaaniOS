from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories

_NOW = datetime.now(UTC)


def test_orchestrator_full_happy_path_with_approval() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)

    # 1. The instruction is planned and an approval is requested; nothing executes.
    result1 = orchestrator.process_text(
        text="Send 200 bags of UltraTech cement to Sharma Builders at the rate quoted day before yesterday and dispatch.",
        now=_NOW,
    )

    assert result1.run.status == VoiceRunStatus.APPROVAL_REQUIRED
    assert result1.decision is not None
    assert result1.decision.decision == DecisionType.APPROVAL_REQUIRED
    assert result1.approval is not None
    assert result1.plan is not None
    assert result1.plan.tool_names == ["create_order", "dispatch_order"]
    assert repos.orders.list_all() == []

    # 2. The owner approves that approval; exactly the stored plan executes.
    result2 = orchestrator.approve(
        run_id=result1.run.run_id,
        approval_id=result1.approval.approval_id,
        approved_by=uuid4(),
        now=_NOW,
    )

    assert result2.run.status == VoiceRunStatus.COMPLETED
    assert result2.executed_tools == ["create_order", "dispatch_order"]
    assert result2.execution_outcome is not None
    assert result2.execution_outcome.success is True
    assert result2.execution_outcome.verification is not None
    assert result2.execution_outcome.verification.status.value == "VERIFIED"

    # Verify database state: dispatch was requested, an invoice was not.
    orders = repos.orders.list_all()
    assert len(orders) == 1
    assert orders[0].subtotal == 84000
    assert repos.invoices.list_all() == []
    dispatches = repos.dispatches.list_all()
    assert len(dispatches) == 1
    assert dispatches[0].status.value == "DISPATCHED"


def test_orchestrator_clarification_flow() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)

    # Ambiguous customer request
    res = orchestrator.process_text(text="Send 200 bags to Sharma.")
    assert res.run.status == VoiceRunStatus.CLARIFICATION_REQUIRED
    assert res.decision is not None
    assert res.decision.decision == DecisionType.CLARIFY


def test_orchestrator_inventory_shortage_escalates_to_handoff() -> None:
    repos = SyntheticRepositories()
    orchestrator = VoiceWorkflowOrchestrator(repositories=repos)

    res = orchestrator.process_text(text="Send 500 bags of ACC cement to Sharma Builders.")
    assert res.run.status == VoiceRunStatus.HANDOFF
    assert res.handoff_case is not None
    assert (
        "shortage" in res.handoff_case.reason.lower()
        or "inventory" in res.handoff_case.reason.lower()
    )
