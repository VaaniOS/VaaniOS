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
from vaaniflow.execution.tools.base import Tool, ToolContext, ToolResult
from vaaniflow.execution.tools.registry import ToolRegistry, create_default_registry
from vaaniflow.execution.verifier import VerificationEngine
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


def committed_record_id(
    repositories: SyntheticRepositories, tool_name: str, idempotency_key: str
) -> UUID | None:
    """The business record a write tool committed under this idempotency key, if any."""
    if tool_name == "create_order":
        order = repositories.orders.get_by_idempotency_key(idempotency_key=idempotency_key)
        return order.order_id if order else None
    if tool_name == "create_invoice_draft":
        invoice = repositories.invoices.get_by_idempotency_key(idempotency_key=idempotency_key)
        return invoice.invoice_id if invoice else None
    if tool_name == "dispatch_order":
        dispatch = repositories.dispatches.get_by_idempotency_key(idempotency_key=idempotency_key)
        return dispatch.dispatch_id if dispatch else None
    return None


class OperatorResolutionError(Exception):
    """An operator resolution does not refer to a resolvable UNKNOWN execution."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExecutionOutcome:
    """Consolidated outcome of an executed business action."""

    success: bool
    execution: ToolExecution
    verification: Verification | None
    tool_result: ToolResult
    message: str
    # True when an UNKNOWN outcome was resolved to SUCCEEDED by read-back.
    reconciled: bool = False


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
        retry_if_not_committed: bool = False,
        now: datetime | None = None,
    ) -> ExecutionOutcome:
        """
        Execute one tool call behind the policy, approval and idempotency gates.

        A previous UNKNOWN execution with the same idempotency key is first
        resolved by reading business state. The tool is invoked again only when
        that read-back proves nothing was committed *and* the caller explicitly
        passes ``retry_if_not_committed=True``; it is never retried blindly.
        """
        current_time = now or datetime.now(UTC)

        # 1. Idempotency guard: Return prior execution if already recorded
        existing_execution = self._repositories.tool_executions.get_by_idempotency_key(
            idempotency_key=idempotency_key
        )
        retry_of: ToolExecution | None = None
        if (
            existing_execution is not None
            and existing_execution.status is ToolExecutionStatus.UNKNOWN
        ):
            unknown_tool = self._registry.get(existing_execution.tool_name)
            if unknown_tool is not None:
                resolved = self._resolve_unknown(
                    tool=unknown_tool,
                    execution=existing_execution,
                    expected_state=expected_state,
                    entity_type=entity_type,
                    tool_result=ToolResult(
                        success=False,
                        outcome_unknown=True,
                        error_code=existing_execution.error_code,
                        error_message=existing_execution.error_message,
                    ),
                    now=current_time,
                )
                committed = self._committed_entity_id(
                    unknown_tool.name, existing_execution.idempotency_key
                )
                if resolved.success or committed is not None or not retry_if_not_committed:
                    return resolved
                # Read-back proved nothing was committed: a retry cannot duplicate.
                retry_of = existing_execution
                existing_execution = None

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
        return self._invoke(
            tool=tool,
            run_id=run_id,
            arguments=arguments,
            idempotency_key=idempotency_key,
            expected_state=expected_state,
            entity_type=entity_type,
            metadata=metadata or {},
            attempt=retry_of.attempt + 1 if retry_of else 1,
            now=current_time,
            execution_id=retry_of.execution_id if retry_of else None,
            prior=retry_of,
        )

    # ------------------------------------------------------------------ #
    # Invocation, verification and outcome resolution
    # ------------------------------------------------------------------ #

    def _invoke(
        self,
        *,
        tool: Tool,
        run_id: UUID,
        arguments: dict[str, Any],
        idempotency_key: str,
        expected_state: dict[str, Any] | None,
        entity_type: str | None,
        metadata: dict[str, Any],
        attempt: int,
        now: datetime,
        execution_id: UUID | None = None,
        prior: ToolExecution | None = None,
    ) -> ExecutionOutcome:
        context = ToolContext(
            run_id=run_id,
            repositories=self._repositories,
            idempotency_key=idempotency_key,
            now=now,
            metadata=metadata,
        )
        execution_id = execution_id or uuid4()
        is_write = tool.side_effect is not ToolSideEffect.READ_ONLY

        try:
            tool_result = tool.execute(arguments=arguments, context=context)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
            # A write that raised may already have been committed: its outcome is
            # unknown, not failed. A read that raised changed nothing.
            tool_result = ToolResult(
                success=False,
                outcome_unknown=is_write,
                error_code="TOOL_EXCEPTION",
                error_message=f"{type(exc).__name__}: {exc}",
            )

        def record(
            status: ToolExecutionStatus,
            *,
            result: dict[str, Any] | None = None,
            error_code: str | None = None,
            error_message: str | None = None,
        ) -> ToolExecution:
            execution = ToolExecution(
                execution_id=execution_id,
                run_id=run_id,
                tool_name=tool.name,
                side_effect=tool.side_effect,
                status=status,
                idempotency_key=idempotency_key,
                arguments=arguments,
                result=result,
                error_code=error_code,
                error_message=error_message,
                attempt=attempt,
                # A retry overwrites the UNKNOWN record; keep what it was.
                prior_status=prior.status if prior else None,
                prior_error_code=prior.error_code if prior else None,
                prior_error_message=prior.error_message if prior else None,
                started_at=now,
                completed_at=now,
                duration_ms=0,
            )
            self._repositories.tool_executions.save(execution=execution)
            return execution

        # 6a. Uncertain outcome: never reported as failed, never blindly retried.
        if not tool_result.success and tool_result.outcome_unknown:
            unknown = record(
                ToolExecutionStatus.UNKNOWN,
                error_code=tool_result.error_code,
                error_message=tool_result.error_message,
            )
            return self._resolve_unknown(
                tool=tool,
                execution=unknown,
                expected_state=expected_state,
                entity_type=entity_type,
                tool_result=tool_result,
                now=now,
            )

        # 6b. Definite failure (CLAUDE.md §2.6: never fake success)
        if not tool_result.success:
            failed = record(
                ToolExecutionStatus.FAILED,
                error_code=tool_result.error_code,
                error_message=tool_result.error_message,
            )
            return ExecutionOutcome(
                success=False,
                execution=failed,
                verification=None,
                tool_result=tool_result,
                message=self._derive_failure_message(tool.name, tool_result.error_message),
            )

        # 7. Read-back verification (CLAUDE.md §2.7 & §19). Mandatory for writes.
        verification: Verification | None = None
        if expected_state is not None or is_write:
            detected_entity_type = entity_type or self._infer_entity_type(tool.name)
            entity_id = self._extract_entity_id(tool_result.data, detected_entity_type)
            verification = self._read_back(
                run_id=run_id,
                execution_id=execution_id,
                entity_type=detected_entity_type,
                entity_id=entity_id,
                expected_state=expected_state,
                now=now,
            )

        if verification is not None and verification.status != VerificationStatus.VERIFIED:
            mismatches_str = "; ".join(verification.mismatches)
            unverified = record(
                ToolExecutionStatus.UNKNOWN,
                result=tool_result.data,
                error_code="VERIFICATION_FAILED",
                error_message=f"Read-back verification failed: {mismatches_str}",
            )
            return ExecutionOutcome(
                success=False,
                execution=unverified,
                verification=verification,
                tool_result=tool_result,
                message=f"Action completed by tool but failed verification: {mismatches_str}",
            )

        succeeded = record(ToolExecutionStatus.SUCCEEDED, result=tool_result.data)
        return ExecutionOutcome(
            success=True,
            execution=succeeded,
            verification=verification,
            tool_result=tool_result,
            message=self._derive_success_message(tool.name, tool_result.data),
        )

    def _read_back(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        entity_type: str,
        entity_id: UUID | None,
        expected_state: dict[str, Any] | None,
        now: datetime,
    ) -> Verification:
        if expected_state is None or entity_id is None:
            problem = (
                "No expected state was supplied for a state-changing tool."
                if expected_state is None
                else f"The tool result does not identify the {entity_type} it wrote."
            )
            verification = Verification(
                verification_id=uuid4(),
                run_id=run_id,
                execution_id=execution_id,
                status=VerificationStatus.UNVERIFIED,
                expected_state=expected_state or {},
                actual_state={},
                mismatches=[problem],
                verifier_version=self._verifier.VERSION,
            )
            self._repositories.verifications.save(verification=verification)
            return verification
        return self._verifier.verify(
            run_id=run_id,
            execution_id=execution_id,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state=expected_state,
            repositories=self._repositories,
            now=now,
        )

    # ------------------------------------------------------------------ #
    # Operator resolution of an UNKNOWN outcome (P2-D)
    # ------------------------------------------------------------------ #

    def resolve_unknown_by_operator(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        attempt: int,
        outcome: ToolExecutionStatus,
        reason: str,
        expected_state: dict[str, Any],
        entity_id: UUID | None = None,
        resolved_by: UUID | None = None,
        now: datetime | None = None,
    ) -> ExecutionOutcome:
        """
        Settle one UNKNOWN execution after an operator checked the business system.

        The operator's word is evidence, not proof:
        - SUCCEEDED requires a record committed by *this* operation (its
          idempotency key) that passes read-back verification; an operation
          that never wrote anything can never be marked successful.
        - FAILED is refused if a record was committed under its key.
        The execution keeps its UNKNOWN history in ``prior_*``.
        """
        current_time = now or datetime.now(UTC)
        execution = self._repositories.tool_executions.get_by_id(execution_id=execution_id)
        if execution is None:
            raise OperatorResolutionError(
                "EXECUTION_NOT_FOUND", f"Tool execution {execution_id} not found."
            )
        if execution.run_id != run_id:
            raise OperatorResolutionError(
                "EXECUTION_RUN_MISMATCH",
                f"Tool execution {execution_id} does not belong to run {run_id}.",
            )
        if execution.status is not ToolExecutionStatus.UNKNOWN:
            code = "ALREADY_RESOLVED" if execution.resolution else "NOT_UNKNOWN"
            raise OperatorResolutionError(
                code,
                f"Tool execution {execution_id} is {execution.status.value}; only an UNKNOWN "
                "outcome can be resolved.",
            )
        if attempt != execution.attempt:
            raise OperatorResolutionError(
                "STALE_RESOLUTION",
                f"Resolution refers to attempt {attempt}, but the execution is at attempt "
                f"{execution.attempt}.",
            )
        if outcome not in {ToolExecutionStatus.SUCCEEDED, ToolExecutionStatus.FAILED}:
            raise OperatorResolutionError(
                "INVALID_RESOLUTION", "An UNKNOWN outcome resolves to SUCCEEDED or FAILED only."
            )

        tool = self._registry.get(execution.tool_name)
        entity_type = self._infer_entity_type(execution.tool_name)
        committed = (
            self._committed_entity_id(tool.name, execution.idempotency_key) if tool else None
        )
        history = {
            "prior_status": execution.status,
            "prior_error_code": execution.error_code,
            "prior_error_message": execution.error_message,
            "resolved_by": resolved_by,
            "resolved_at": current_time,
            "resolution_reason": reason,
            "completed_at": current_time,
        }

        if outcome is ToolExecutionStatus.FAILED:
            if committed is not None:
                raise OperatorResolutionError(
                    "RESOLUTION_CONTRADICTED",
                    f"A {entity_type} ({committed}) was committed under this operation's key; "
                    "it cannot be marked as failed.",
                )
            failed = execution.model_copy(
                update={
                    **history,
                    "status": ToolExecutionStatus.FAILED,
                    "error_code": "OPERATOR_CONFIRMED_FAILURE",
                    "error_message": reason,
                    "resolution": "OPERATOR_CONFIRMED_FAILURE",
                }
            )
            self._repositories.tool_executions.save(execution=failed)
            return ExecutionOutcome(
                success=False,
                execution=failed,
                verification=None,
                tool_result=ToolResult(
                    success=False, error_code="OPERATOR_CONFIRMED_FAILURE", error_message=reason
                ),
                message=f"Operator confirmed {execution.tool_name} did not take effect: {reason}",
            )

        target = entity_id or committed
        if target is None:
            raise OperatorResolutionError(
                "RESOLUTION_NOT_VERIFIED",
                f"No {entity_type} was committed by this operation; success cannot be recorded.",
            )
        if committed is not None and target != committed:
            raise OperatorResolutionError(
                "RESOLUTION_NOT_VERIFIED",
                f"{entity_type} {target} is not the record this operation committed ({committed}).",
            )
        # Only a record stamped with this operation's idempotency key proves that
        # this operation wrote it; an equivalent record from elsewhere does not.
        owner = self._record_idempotency_key(entity_type, target)
        if owner != execution.idempotency_key:
            raise OperatorResolutionError(
                "RESOLUTION_NOT_VERIFIED",
                f"{entity_type} {target} was not created by this operation.",
            )
        verification = self._read_back(
            run_id=execution.run_id,
            execution_id=execution.execution_id,
            entity_type=entity_type,
            entity_id=target,
            expected_state=expected_state,
            now=current_time,
        )
        if verification.status is not VerificationStatus.VERIFIED:
            raise OperatorResolutionError(
                "RESOLUTION_NOT_VERIFIED",
                f"Read-back of {entity_type} {target} did not verify: "
                + "; ".join(verification.mismatches),
            )
        data = dict(verification.actual_state)
        succeeded = execution.model_copy(
            update={
                **history,
                "status": ToolExecutionStatus.SUCCEEDED,
                "result": data,
                "error_code": None,
                "error_message": None,
                "resolution": "OPERATOR_CONFIRMED_SUCCESS",
            }
        )
        self._repositories.tool_executions.save(execution=succeeded)
        return ExecutionOutcome(
            success=True,
            execution=succeeded,
            verification=verification,
            tool_result=ToolResult(success=True, data=data),
            message=(
                f"Operator resolution verified by read-back: "
                f"{self._derive_success_message(execution.tool_name, data)}"
            ),
        )

    def _record_idempotency_key(self, entity_type: str, entity_id: UUID) -> str | None:
        repos = self._repositories
        record: Any
        if entity_type == "order":
            record = repos.orders.get_by_id(order_id=entity_id)
        elif entity_type == "invoice":
            record = repos.invoices.get_by_id(invoice_id=entity_id)
        elif entity_type == "dispatch":
            record = repos.dispatches.get_by_id(dispatch_id=entity_id)
        else:
            record = None
        return record.idempotency_key if record is not None else None

    def _committed_entity_id(self, tool_name: str, idempotency_key: str) -> UUID | None:
        """Find the record a write created under this idempotency key, if any."""
        return committed_record_id(self._repositories, tool_name, idempotency_key)

    def _resolve_unknown(
        self,
        *,
        tool: Tool,
        execution: ToolExecution,
        expected_state: dict[str, Any] | None,
        entity_type: str | None,
        tool_result: ToolResult,
        now: datetime,
    ) -> ExecutionOutcome:
        """
        Resolve an UNKNOWN outcome by reading business state, never by re-invoking.

        Committed and verified -> SUCCEEDED (reconciled). Absent or not
        verifiable -> stays UNKNOWN; the caller must not report success or failure.
        """
        detected_entity_type = entity_type or self._infer_entity_type(tool.name)
        entity_id = self._committed_entity_id(tool.name, execution.idempotency_key)
        if entity_id is None:
            return ExecutionOutcome(
                success=False,
                execution=execution,
                verification=None,
                tool_result=tool_result,
                message=(
                    f"Outcome of {tool.name} is unknown: {execution.error_message} "
                    "No committed record was found under its idempotency key. "
                    "It was not retried automatically."
                ),
            )

        verification = self._read_back(
            run_id=execution.run_id,
            execution_id=execution.execution_id,
            entity_type=detected_entity_type,
            entity_id=entity_id,
            expected_state=expected_state,
            now=now,
        )
        if verification.status is not VerificationStatus.VERIFIED:
            return ExecutionOutcome(
                success=False,
                execution=execution,
                verification=verification,
                tool_result=tool_result,
                message=(
                    f"Outcome of {tool.name} is unknown: a record exists under its idempotency "
                    f"key but does not verify ({'; '.join(verification.mismatches)})."
                ),
            )

        data = dict(verification.actual_state)
        reconciled = execution.model_copy(
            update={
                "status": ToolExecutionStatus.SUCCEEDED,
                "result": data,
                "error_code": None,
                "error_message": None,
                "completed_at": now,
                # The record keeps that this outcome was once UNKNOWN, and why.
                "reconciled": True,
                "resolution": "RECONCILED_BY_READ_BACK",
                "resolved_at": now,
                "prior_status": execution.status,
                "prior_error_code": execution.error_code,
                "prior_error_message": execution.error_message,
            }
        )
        self._repositories.tool_executions.save(execution=reconciled)
        return ExecutionOutcome(
            success=True,
            execution=reconciled,
            verification=verification,
            tool_result=ToolResult(success=True, data=data),
            message=(
                f"{tool.name} did not respond, but read-back found its committed record "
                f"and verified it. {self._derive_success_message(tool.name, data)}"
            ),
            reconciled=True,
        )

    def _derive_failure_message(self, tool_name: str, error_message: str | None) -> str:
        err = error_message or "Unknown execution error."
        if tool_name == "issue_invoice":
            return (
                f"The invoice could not be created. I have kept the validated draft. (Error: {err})"
            )
        elif tool_name == "dispatch_order":
            # State only what is known: no dispatch was recorded. The order's own
            # status is reported from its record by the caller, never assumed here.
            return f"The dispatch could not be executed; no dispatch was recorded. (Error: {err})"
        elif tool_name == "create_order":
            return f"The order could not be created; no order was recorded. (Error: {err})"
        elif tool_name == "create_invoice_draft":
            return (
                f"The invoice draft could not be created; no invoice was recorded. (Error: {err})"
            )
        return f"Action '{tool_name}' failed: {err}"

    def _derive_success_message(self, tool_name: str, data: dict[str, Any]) -> str:
        # Wording follows the record's actual status (P2-F): a DRAFT is a draft.
        status = data.get("status")
        if tool_name == "create_order":
            return f"Order {data.get('order_id')} recorded with status {status}."
        elif tool_name == "create_invoice_draft":
            return (
                f"Invoice {data.get('invoice_id')} recorded with status {status} "
                f"(total ₹{data.get('total')}); it has not been issued."
            )
        elif tool_name == "issue_invoice":
            return f"Invoice {data.get('invoice_id')} issued successfully for total ₹{data.get('total')}."
        elif tool_name == "dispatch_order":
            return f"Dispatch {data.get('dispatch_id')} recorded with status {status}."
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
