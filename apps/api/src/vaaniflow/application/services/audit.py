"""
End-to-end audit trail of one run (P2-E).

Assembles records that already exist, linked by run id, plan id, approval id,
idempotency key and order id. It answers, from stored evidence only:
what was said, what was understood, what context was resolved, what was
validated, why approval was required, what was approved and by whom, whether
anything changed between approval and execution, what ran, what each tool
returned, what was verified, and what business state resulted.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from vaaniflow.domain.models.tool_execution import ToolExecution, ToolExecutionStatus
from vaaniflow.execution.service import committed_record_id
from vaaniflow.handoff.service import interpret_semantic_state
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


class RunAuditService:
    def __init__(self, repositories: SyntheticRepositories) -> None:
        self._repositories = repositories

    def build(self, *, run_id: UUID) -> dict[str, Any] | None:
        repos = self._repositories
        run = repos.runs.get_by_id(run_id=run_id)
        if run is None:
            return None

        instructions = [
            {
                "transcript_id": str(u.transcript.transcript_id),
                "text": u.transcript.text,
                "spoken_at": u.transcript.created_at.isoformat(),
                "actionability": u.actionability.value,
                "evaluation_reasons": [r.model_dump(mode="json") for r in u.evaluation.reasons],
                "understood": interpret_semantic_state(u.semantic_state),
            }
            for u in repos.understand_results.list_by_run(run_id=run_id)
        ]

        plans = []
        for pending in repos.pending_executions.list_by_run(run_id=run_id):
            approval = repos.approvals.get_by_id(approval_id=pending.approval_id)
            plan = pending.plan
            plans.append(
                {
                    "plan_id": str(plan.plan_id),
                    "fingerprint": plan.fingerprint,
                    "snapshot_version": plan.snapshot_version,
                    "from_transcript_id": str(pending.understand_result.transcript.transcript_id),
                    "executable_actions": [a.value for a in plan.executable_actions],
                    "excluded_negated_actions": [a.value for a in plan.excluded_negated_actions],
                    "unsupported_actions": [a.value for a in plan.unsupported_actions],
                    "tool_calls": [c.model_dump(mode="json") for c in plan.tool_calls],
                    "resolved_context": pending.context_snapshot,
                    "validation": pending.validation_result.model_dump(mode="json")
                    if pending.validation_result
                    else None,
                    "approval_required_because": pending.decision_reason,
                    "approval": approval.model_dump(mode="json") if approval else None,
                    "changed_between_approval_and_execution": _snapshot_change(approval),
                }
            )

        executions = repos.tool_executions.list_by_run(run_id=run_id)
        verifications = repos.verifications.list_by_run(run_id=run_id)
        orders = [o for o in repos.orders.list_all() if o.source_run_id == run_id]
        order_ids = {o.order_id for o in orders}
        invoices = [i for i in repos.invoices.list_all() if i.order_id in order_ids]
        dispatches = [d for d in repos.dispatches.list_all() if d.order_id in order_ids]
        trace = repos.traces.get_trace(run_id=run_id)

        return {
            "run": run.model_dump(mode="json"),
            "instructions": instructions,
            "clarifications": [
                c.model_dump(mode="json", exclude={"understand_result"})
                for c in repos.clarifications.list_by_run(run_id=run_id)
            ],
            "confirmations": [
                c.model_dump(mode="json", exclude={"understand_result"})
                for c in repos.pending_confirmations.list_by_run(run_id=run_id)
            ],
            "plans": plans,
            "tool_executions": [e.model_dump(mode="json") for e in executions],
            "reconciliation": self._reconcile(executions),
            "verifications": [v.model_dump(mode="json") for v in verifications],
            "business_records": {
                "orders": [o.model_dump(mode="json") for o in orders],
                "invoices": [i.model_dump(mode="json") for i in invoices],
                "dispatches": [d.model_dump(mode="json") for d in dispatches],
            },
            "handoffs": [
                h.model_dump(mode="json") for h in repos.handoffs.list_by_run(run_id=run_id)
            ],
            "trace": [e.model_dump(mode="json") for e in trace.events] if trace else [],
        }

    def _reconcile(self, executions: list[ToolExecution]) -> dict[str, Any]:
        """
        Compare each recorded write outcome with current business state (F4).

        A write recorded as FAILED whose idempotency key now has a committed record
        is a contradiction (e.g. an operator resolved an UNKNOWN as FAILED and the
        business system committed late). It is reported, never auto-corrected: the
        recorded outcome and its resolution stay as they were.
        """
        contradictions = []
        for execution in executions:
            if execution.status is not ToolExecutionStatus.FAILED:
                continue
            record_id = committed_record_id(
                self._repositories, execution.tool_name, execution.idempotency_key
            )
            if record_id is None:
                continue
            contradictions.append(
                {
                    "code": "FAILED_BUT_RECORD_EXISTS",
                    "execution_id": str(execution.execution_id),
                    "tool_name": execution.tool_name,
                    "recorded_status": execution.status.value,
                    "resolution": execution.resolution,
                    "resolved_by": str(execution.resolved_by) if execution.resolved_by else None,
                    "committed_record_id": str(record_id),
                    "message": (
                        f"{execution.tool_name} is recorded as FAILED, but a record "
                        f"({record_id}) exists under its idempotency key. The business "
                        "state shows the write took effect; an operator must review it."
                    ),
                }
            )
        return {"consistent": not contradictions, "contradictions": contradictions}


def _snapshot_change(approval: Any) -> dict[str, Any] | None:
    if approval is None or approval.approved_snapshot_version is None:
        return None
    return {
        "requested_snapshot": approval.snapshot_version,
        "approval_time_snapshot": approval.approved_snapshot_version,
        "changed": approval.snapshot_version != approval.approved_snapshot_version,
        "expiry_reason": approval.expiry_reason,
    }
