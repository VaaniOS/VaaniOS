from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.tool_execution import (
    ToolExecution,
    ToolExecutionStatus,
    ToolSideEffect,
)
from vaaniflow.domain.models.verification import Verification, VerificationStatus
from vaaniflow.domain.policies.decision import Decision, DecisionType
from vaaniflow.execution.approval import ApprovalService
from vaaniflow.execution.tools.base import ToolContext, ToolResult
from vaaniflow.execution.tools.registry import ToolRegistry, create_default_registry
from vaaniflow.execution.verifier import VerificationEngine
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


@dataclass
class ExecutionOutcome:
    """Consolidated outcome of an executed business action."""

    success: bool
    execution: ToolExecution
    verification: Verification | None
    tool_result: ToolResult
    message: str


class ExecutionService:
    """
    Execution orchestrator for business tools.

    Guarantees:
    1. Deterministic policy boundary: LLM proposals cannot execute without an ALLOWED Decision.
    2. Explicit approval check: Consequential actions require an approved snapshot.
    3. Idempotency safety: Re-running with the same key prevents duplicate business side-effects.
    4. Never fake success: Tool failures preserve draft state and clearly report failures.
    5. Post-execution verification: Verifies read-back state from repository.
    """

    def __init__(
        self,
        repositories: SyntheticRepositories,
        registry: ToolRegistry | None = None,
        verifier: VerificationEngine | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._repositories = repositories
        self._registry = registry or create_default_registry()
        self._verifier = verifier or VerificationEngine()
        self._approval_service = approval_service or ApprovalService(repositories)

    def execute(
        self,
        *,
        run_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        decision: Decision,
        approval: Approval | None = None,
        current_snapshot_version: str | None = None,
        expected_state: dict[str, Any] | None = None,
        entity_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ExecutionOutcome:
        current_time = now or datetime.now(UTC)

        # 1. Idempotency guard: Return prior execution if already recorded
        existing_execution = self._repositories.tool_executions.get_by_idempotency_key(
            idempotency_key=idempotency_key
        )
        if existing_execution is not None:
            existing_verification = self._repositories.verifications.get_by_execution_id(
                execution_id=existing_execution.execution_id
            )
            success = existing_execution.status == ToolExecutionStatus.SUCCEEDED
            msg = (
                "Action already executed (idempotency match)."
                if success
                else f"Previous execution failed: {existing_execution.error_message}"
            )
            return ExecutionOutcome(
                success=success,
                execution=existing_execution,
                verification=existing_verification,
                tool_result=ToolResult(
                    success=success,
                    data=existing_execution.result or {},
                    error_code=existing_execution.error_code,
                    error_message=existing_execution.error_message,
                ),
                message=msg,
            )

        # 2. Tool Lookup
        tool = self._registry.get(tool_name)
        side_effect = tool.side_effect if tool else ToolSideEffect.READ_ONLY
        if tool is None:
            failed_execution = ToolExecution(
                execution_id=uuid4(),
                run_id=run_id,
                tool_name=tool_name,
                side_effect=side_effect,
                status=ToolExecutionStatus.FAILED,
                idempotency_key=idempotency_key,
                arguments=arguments,
                error_code="TOOL_NOT_FOUND",
                error_message=f"Tool '{tool_name}' is not registered.",
                started_at=current_time,
                completed_at=current_time,
                duration_ms=0,
            )
            self._repositories.tool_executions.save(execution=failed_execution)
            return ExecutionOutcome(
                success=False,
                execution=failed_execution,
                verification=None,
                tool_result=ToolResult(
                    success=False,
                    error_code="TOOL_NOT_FOUND",
                    error_message=f"Tool '{tool_name}' is not registered.",
                ),
                message=f"Action blocked: Tool '{tool_name}' is not registered in the system.",
            )

        # 3. Policy Gate
        if decision.decision != DecisionType.EXECUTE or not decision.allowed:
            blocked_execution = ToolExecution(
                execution_id=uuid4(),
                run_id=run_id,
                tool_name=tool_name,
                side_effect=tool.side_effect,
                status=ToolExecutionStatus.FAILED,
                idempotency_key=idempotency_key,
                arguments=arguments,
                error_code="POLICY_BLOCKED",
                error_message=f"Action rejected by policy: {decision.reason}",
                started_at=current_time,
                completed_at=current_time,
                duration_ms=0,
            )
            self._repositories.tool_executions.save(execution=blocked_execution)
            return ExecutionOutcome(
                success=False,
                execution=blocked_execution,
                verification=None,
                tool_result=ToolResult(
                    success=False,
                    error_code="POLICY_BLOCKED",
                    error_message=decision.reason,
                ),
                message=f"Action blocked by policy: {decision.reason}",
            )

        # 4. Explicit Approval Gate
        if decision.requires_approval or tool.side_effect in {
            ToolSideEffect.IRREVERSIBLE_WRITE,
            ToolSideEffect.REVERSIBLE_WRITE,
        }:
            if approval is None or approval.status != ApprovalStatus.APPROVED:
                unapproved_execution = ToolExecution(
                    execution_id=uuid4(),
                    run_id=run_id,
                    tool_name=tool_name,
                    side_effect=tool.side_effect,
                    status=ToolExecutionStatus.FAILED,
                    idempotency_key=idempotency_key,
                    arguments=arguments,
                    error_code="APPROVAL_REQUIRED",
                    error_message="Consequential action requires explicit owner approval.",
                    started_at=current_time,
                    completed_at=current_time,
                    duration_ms=0,
                )
                self._repositories.tool_executions.save(execution=unapproved_execution)
                return ExecutionOutcome(
                    success=False,
                    execution=unapproved_execution,
                    verification=None,
                    tool_result=ToolResult(
                        success=False,
                        error_code="APPROVAL_REQUIRED",
                        error_message="Action requires explicit owner approval.",
                    ),
                    message="Action blocked: Explicit owner approval is required before execution.",
                )

            # Check snapshot validity (Scenario H: environment change check)
            if (
                current_snapshot_version is not None
                and approval.snapshot_version != current_snapshot_version
            ):
                expired_execution = ToolExecution(
                    execution_id=uuid4(),
                    run_id=run_id,
                    tool_name=tool_name,
                    side_effect=tool.side_effect,
                    status=ToolExecutionStatus.FAILED,
                    idempotency_key=idempotency_key,
                    arguments=arguments,
                    error_code="APPROVAL_EXPIRED",
                    error_message="Underlying transaction state changed after approval was granted.",
                    started_at=current_time,
                    completed_at=current_time,
                    duration_ms=0,
                )
                self._repositories.tool_executions.save(execution=expired_execution)
                return ExecutionOutcome(
                    success=False,
                    execution=expired_execution,
                    verification=None,
                    tool_result=ToolResult(
                        success=False,
                        error_code="APPROVAL_EXPIRED",
                        error_message="Snapshot version mismatch: context changed after approval.",
                    ),
                    message="Action blocked: Business state changed since approval was given. Re-approval required.",
                )

        # 5. Tool Invocation
        context = ToolContext(
            run_id=run_id,
            repositories=self._repositories,
            idempotency_key=idempotency_key,
            now=current_time,
            metadata=metadata or {},
        )

        tool_result = tool.execute(arguments=arguments, context=context)
        finished_time = current_time
        duration_ms = int((finished_time - current_time).total_seconds() * 1000)

        # 6. Failure Handling (CLAUDE.md §2.6: Never Fake Success)
        if not tool_result.success:
            failed_execution = ToolExecution(
                execution_id=uuid4(),
                run_id=run_id,
                tool_name=tool_name,
                side_effect=tool.side_effect,
                status=ToolExecutionStatus.FAILED,
                idempotency_key=idempotency_key,
                arguments=arguments,
                error_code=tool_result.error_code,
                error_message=tool_result.error_message,
                started_at=current_time,
                completed_at=finished_time,
                duration_ms=duration_ms,
            )
            self._repositories.tool_executions.save(execution=failed_execution)

            # Accurate message based on action
            failure_message = self._derive_failure_message(tool_name, tool_result.error_message)

            return ExecutionOutcome(
                success=False,
                execution=failed_execution,
                verification=None,
                tool_result=tool_result,
                message=failure_message,
            )

        # 7. Read-Back Verification (CLAUDE.md §2.7 & §19)
        verification: Verification | None = None
        execution_id = uuid4()

        if expected_state is not None:
            detected_entity_type = entity_type or self._infer_entity_type(tool_name)
            entity_id = self._extract_entity_id(tool_result.data, detected_entity_type)

            if entity_id is not None:
                verification = self._verifier.verify(
                    run_id=run_id,
                    execution_id=execution_id,
                    entity_type=detected_entity_type,
                    entity_id=entity_id,
                    expected_state=expected_state,
                    repositories=self._repositories,
                    now=finished_time,
                )

        # Determine outcome based on verification
        if verification is not None and verification.status != VerificationStatus.VERIFIED:
            mismatches_str = "; ".join(verification.mismatches)
            verified_failed_execution = ToolExecution(
                execution_id=execution_id,
                run_id=run_id,
                tool_name=tool_name,
                side_effect=tool.side_effect,
                status=ToolExecutionStatus.UNKNOWN,
                idempotency_key=idempotency_key,
                arguments=arguments,
                result=tool_result.data,
                error_code="VERIFICATION_FAILED",
                error_message=f"Read-back verification failed: {mismatches_str}",
                started_at=current_time,
                completed_at=finished_time,
                duration_ms=duration_ms,
            )
            self._repositories.tool_executions.save(execution=verified_failed_execution)
            return ExecutionOutcome(
                success=False,
                execution=verified_failed_execution,
                verification=verification,
                tool_result=tool_result,
                message=f"Action completed by tool but failed verification: {mismatches_str}",
            )

        # Success path
        successful_execution = ToolExecution(
            execution_id=execution_id,
            run_id=run_id,
            tool_name=tool_name,
            side_effect=tool.side_effect,
            status=ToolExecutionStatus.SUCCEEDED,
            idempotency_key=idempotency_key,
            arguments=arguments,
            result=tool_result.data,
            started_at=current_time,
            completed_at=finished_time,
            duration_ms=duration_ms,
        )
        self._repositories.tool_executions.save(execution=successful_execution)

        return ExecutionOutcome(
            success=True,
            execution=successful_execution,
            verification=verification,
            tool_result=tool_result,
            message=self._derive_success_message(tool_name, tool_result.data),
        )

    def _derive_failure_message(self, tool_name: str, error_message: str | None) -> str:
        err = error_message or "Unknown execution error."
        if tool_name == "issue_invoice":
            return (
                f"The invoice could not be created. I have kept the validated draft. (Error: {err})"
            )
        elif tool_name == "dispatch_order":
            return f"The dispatch could not be executed. Order remains confirmed but not dispatched. (Error: {err})"
        elif tool_name == "create_order":
            return f"The order could not be created. (Error: {err})"
        return f"Action '{tool_name}' failed: {err}"

    def _derive_success_message(self, tool_name: str, data: dict[str, Any]) -> str:
        if tool_name == "create_order":
            return f"Order {data.get('order_id')} created successfully."
        elif tool_name == "create_invoice_draft":
            return (
                f"Invoice draft {data.get('invoice_id')} generated for total ₹{data.get('total')}."
            )
        elif tool_name == "issue_invoice":
            return f"Invoice {data.get('invoice_id')} issued successfully for total ₹{data.get('total')}."
        elif tool_name == "dispatch_order":
            return f"Dispatch {data.get('dispatch_id')} confirmed with warehouse."
        return f"Tool '{tool_name}' completed successfully."

    def _infer_entity_type(self, tool_name: str) -> str:
        if "invoice" in tool_name:
            return "invoice"
        elif "dispatch" in tool_name:
            return "dispatch"
        elif "order" in tool_name:
            return "order"
        return "order"

    def _extract_entity_id(self, data: dict[str, Any], entity_type: str) -> UUID | None:
        key = f"{entity_type}_id"
        val = data.get(key)
        if val:
            try:
                return UUID(str(val))
            except (ValueError, TypeError):
                return None
        return None
