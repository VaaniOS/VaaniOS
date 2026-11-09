from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.schemas.audio_preprocessing import AudioPreprocessingInput
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.context.service import ContextResolutionOutput, ContextResolutionService
from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.handoff import HandoffCase
from vaaniflow.domain.models.validation import ValidationResult
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus
from vaaniflow.domain.policies.decision import Decision, DecisionReasonCode, DecisionType
from vaaniflow.domain.policies.risk import RiskAssessment
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.semantic import ReferenceType, SemanticState
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import EvaluationReasonCode, UnderstandResult
from vaaniflow.execution.approval import ApprovalService
from vaaniflow.execution.plan import (
    ExecutionPlan,
    PendingExecution,
    PlanningError,
    build_plan,
    business_snapshot_version,
)
from vaaniflow.execution.service import ExecutionOutcome, ExecutionService
from vaaniflow.handoff.service import HandoffService
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.policy.engine import PolicyEngine
from vaaniflow.policy.risk import RiskAssessor
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator
from vaaniflow.traces.models import TraceStage
from vaaniflow.traces.service import TraceService
from vaaniflow.validation.engine import ValidationEngine

# PARTIAL references ACT can ground against business records (historical quotes).
_RESOLVABLE_REFERENCES = frozenset({ReferenceType.HISTORICAL_PRICE, ReferenceType.HISTORICAL_QUOTE})

_EXPECTED_STATE_ENTITY = {"dispatch_order": "dispatch"}


class ApprovalFlowError(Exception):
    """An approval/rejection request does not refer to a pending approval of this run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class WorkflowResult:
    """Standardized composite result returned after processing a voice run."""

    run: VoiceRun
    understand_result: UnderstandResult | None
    business_context: BusinessContext | None
    validation_result: ValidationResult | None
    risk_assessment: RiskAssessment | None
    decision: Decision | None
    approval: Approval | None
    handoff_case: HandoffCase | None
    execution_outcome: ExecutionOutcome | None
    message: str
    snapshot_version: str | None = None
    plan: ExecutionPlan | None = None
    executed_tools: list[str] = field(default_factory=list)


@dataclass
class _ActAssessment:
    context: ContextResolutionOutput
    validation: ValidationResult
    risk: RiskAssessment
    decision: Decision
    snapshot_version: str


class VoiceWorkflowOrchestrator:
    """
    End-to-end orchestrator connecting UNDERSTAND and ACT layers.

    Guarantees:
    1. Only COMPLETE, or PARTIAL whose references ACT can ground, reaches ACT.
    2. Tools come from an explicit plan built from requested − negated actions.
    3. Every business write requires a persisted approval bound to that plan,
       its run and a deterministic business snapshot; approval re-validates.
    4. Missing business facts fail safely; nothing is defaulted.
    5. Never fakes success on failures.
    """

    def __init__(
        self,
        repositories: SyntheticRepositories,
        compiler: SemanticCompiler | None = None,
        evaluator: InputEvaluator | None = None,
        context_resolver: ContextResolutionService | None = None,
        validation_engine: ValidationEngine | None = None,
        risk_assessor: RiskAssessor | None = None,
        policy_engine: PolicyEngine | None = None,
        approval_service: ApprovalService | None = None,
        execution_service: ExecutionService | None = None,
        handoff_service: HandoffService | None = None,
        trace_service: TraceService | None = None,
        preprocess_audio_service: PreprocessAudioService | None = None,
        transcribe_audio_service: TranscribeAudioService | None = None,
    ) -> None:
        self.repositories = repositories
        self.compiler = compiler or SemanticCompiler()
        self.evaluator = evaluator or InputEvaluator()
        self.context_resolver = context_resolver or ContextResolutionService(
            customer_repo=repositories.customers,
            product_repo=repositories.products,
            quote_repo=repositories.quotes,
            inventory_repo=repositories.inventory,
            tax_rule_repo=repositories.tax_rules,
            timezone_str="Asia/Kolkata",
        )
        self.validation_engine = validation_engine or ValidationEngine()
        self.risk_assessor = risk_assessor or RiskAssessor()
        self.policy_engine = policy_engine or PolicyEngine()
        self.approval_service = approval_service or ApprovalService(repositories)
        self.execution_service = execution_service or ExecutionService(repositories)
        self.handoff_service = handoff_service or HandoffService(repositories)
        self.trace_service = trace_service or TraceService(repositories.traces)
        self.preprocess_audio_service = preprocess_audio_service
        self.transcribe_audio_service = transcribe_audio_service

    # ------------------------------------------------------------------ #
    # Run lifecycle
    # ------------------------------------------------------------------ #

    def start_run(self, *, run_id: UUID | None = None, now: datetime | None = None) -> VoiceRun:
        """Create and persist a new VoiceRun aggregate."""
        t = now or datetime.now(UTC)
        run = VoiceRun(
            run_id=run_id or uuid4(),
            status=VoiceRunStatus.CREATED,
            created_at=t,
            updated_at=t,
        )
        self.repositories.runs.save(run=run)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.INGESTED,
            output_summary=f"Run {run.run_id} created.",
            timestamp=t,
        )
        return run

    def process_text(
        self,
        *,
        text: str,
        run_id: UUID | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Interpret a text instruction and decide what may happen.

        This never executes a business write: writes are planned, persisted and
        returned as an approval request that must be approved via approve().
        """
        t = now or datetime.now(UTC)
        run = self.repositories.runs.get_by_id(run_id=run_id) if run_id else None
        if run is None:
            run = self.start_run(run_id=run_id, now=t)
        self._set_status(run, VoiceRunStatus.PROCESSING, t)

        # 1. UNDERSTAND
        understand_result = self._understand(text=text, run=run, now=t)
        semantic_state = understand_result.semantic_state
        evaluation = understand_result.evaluation

        # 2. Safety / actionability gate (before any business lookup)
        if evaluation.actionability is Actionability.BLOCKED:
            run.failure_code = "INPUT_BLOCKED"
            run.failure_message = "; ".join(r.message for r in evaluation.reasons)
            self._set_status(run, VoiceRunStatus.BLOCKED, t)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.BLOCKED,
                error_code="INPUT_BLOCKED",
                error_message=run.failure_message,
                timestamp=t,
            )
            return self._result(
                run, understand_result, message=f"Request blocked: {run.failure_message}"
            )

        if evaluation.actionability is Actionability.CLARIFICATION_REQUIRED:
            reasons = [
                r.message
                for r in evaluation.reasons
                if r.effect is Actionability.CLARIFICATION_REQUIRED
            ]
            code = (
                DecisionReasonCode.AMBIGUOUS_INPUT
                if semantic_state.ambiguities
                or any(
                    r.code is EvaluationReasonCode.SEMANTIC_AMBIGUITY for r in evaluation.reasons
                )
                else DecisionReasonCode.MISSING_INFORMATION
            )
            return self._clarify(
                run,
                understand_result,
                code=code,
                reason="Clarification required before any action: " + "; ".join(reasons),
                now=t,
            )

        if len(semantic_state.items) > 1:
            return self._clarify(
                run,
                understand_result,
                code=DecisionReasonCode.MISSING_INFORMATION,
                reason=(
                    f"The request contains {len(semantic_state.items)} line items; "
                    "multi-item execution is not supported. Send one item per request."
                ),
                now=t,
            )

        unresolvable = self._unresolvable_partial_references(understand_result)
        if unresolvable:
            return self._clarify(
                run,
                understand_result,
                code=DecisionReasonCode.MISSING_INFORMATION,
                reason=(
                    "The request depends on context that cannot be resolved from business "
                    "records: " + ", ".join(unresolvable)
                ),
                now=t,
            )

        # 3–6. Context → validation → risk → policy
        act = self._assess(semantic_state=semantic_state, run=run, is_approved=False, now=t)
        decision = act.decision

        if decision.decision is DecisionType.CLARIFY:
            self._set_status(run, VoiceRunStatus.CLARIFICATION_REQUIRED, t)
            return self._result(run, understand_result, act=act, message=decision.reason)

        if decision.decision is DecisionType.CONFIRM:
            self._set_status(run, VoiceRunStatus.APPROVAL_REQUIRED, t)
            return self._result(
                run, understand_result, act=act, message=f"Confirmation required: {decision.reason}"
            )

        if decision.decision is DecisionType.HUMAN_HANDOFF:
            self._set_status(run, VoiceRunStatus.HANDOFF, t)
            handoff_case = self.handoff_service.create_case_from_evaluation(
                run_id=run.run_id,
                original_request=text,
                validation_result=act.validation,
                risk_assessment=act.risk,
                decision=decision,
                semantic_state=semantic_state,
                customer_id=act.context.business_context.customer.customer.customer_id
                if act.context.business_context.customer
                else None,
                now=t,
            )
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.HANDOFF_CREATED,
                output_summary=f"Handoff case {handoff_case.handoff_id} created: {handoff_case.reason}",
                timestamp=t,
            )
            return self._result(
                run,
                understand_result,
                act=act,
                handoff_case=handoff_case,
                message=f"Escalated to human operator: {decision.reason}",
            )

        if decision.decision is DecisionType.BLOCKED:
            return self._block(
                run,
                understand_result,
                act=act,
                code=decision.reason_code.value,
                reason=decision.reason,
                now=t,
            )

        # PARTIAL: the historical-price reference must be grounded in a quote.
        if evaluation.actionability is Actionability.PARTIAL and (
            act.context.business_context.resolved_price is None
            or act.context.business_context.resolved_price.source_quote_id is None
        ):
            return self._clarify(
                run,
                understand_result,
                code=DecisionReasonCode.MISSING_INFORMATION,
                reason="The referenced historical rate could not be grounded in a quote record.",
                act=act,
                now=t,
            )

        # 7. Explicit plan from requested − negated actions
        try:
            plan = build_plan(
                run_id=run.run_id,
                semantic_state=semantic_state,
                business_context=act.context.business_context,
                tax_calculation=act.context.tax_calculation,
            )
        except PlanningError as exc:
            return self._block(
                run,
                understand_result,
                act=act,
                code="MISSING_BUSINESS_FACT",
                reason=f"Cannot plan execution safely: {exc}",
                now=t,
            )

        if not plan.has_writes and not plan.read_actions and not plan.unsupported_actions:
            return self._clarify(
                run,
                understand_result,
                code=DecisionReasonCode.MISSING_INFORMATION,
                reason="No executable action was requested.",
                act=act,
                plan=plan,
                now=t,
            )

        # Read-only requests are answered from already-resolved business facts.
        if not plan.has_writes:
            return self._finish_without_writes(run, understand_result, act=act, plan=plan, now=t)

        # 8. Business writes always require an approval bound to this exact plan.
        approval = self.approval_service.request_approval(
            run_id=run.run_id,
            requested_by=uuid4(),
            snapshot_version=plan.snapshot_version,
            now=t,
        )
        self.repositories.pending_executions.save(
            pending=PendingExecution(
                approval_id=approval.approval_id,
                plan=plan,
                understand_result=understand_result,
                created_at=t,
            )
        )
        approval_decision = Decision(
            decision_id=uuid4(),
            run_id=run.run_id,
            decision=DecisionType.APPROVAL_REQUIRED,
            reason_code=DecisionReasonCode.APPROVAL_REQUIRED,
            reason=(
                "Planned business writes require explicit owner approval: "
                + ", ".join(plan.tool_names)
            ),
            allowed=False,
            requires_approval=True,
            policy_version=decision.policy_version,
        )
        self._set_status(run, VoiceRunStatus.APPROVAL_REQUIRED, t)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.APPROVAL_REQUESTED,
            output_summary=(
                f"Approval {approval.approval_id} requested for plan {plan.plan_id} "
                f"(tools={plan.tool_names}, unsupported={[a.value for a in plan.unsupported_actions]}, "
                f"snapshot={plan.snapshot_version})"
            ),
            timestamp=t,
        )
        unsupported = (
            f" Not supported and will not be performed: "
            f"{', '.join(a.value for a in plan.unsupported_actions)}."
            if plan.unsupported_actions
            else ""
        )
        return WorkflowResult(
            run=run,
            understand_result=understand_result,
            business_context=act.context.business_context,
            validation_result=act.validation,
            risk_assessment=act.risk,
            decision=approval_decision,
            approval=approval,
            handoff_case=None,
            execution_outcome=None,
            message=f"Approval required for planned actions: {', '.join(plan.tool_names)}."
            + unsupported,
            snapshot_version=plan.snapshot_version,
            plan=plan,
        )

    # ------------------------------------------------------------------ #
    # Approval
    # ------------------------------------------------------------------ #

    def approve(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved_by: UUID,
        simulated_faults: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Approve a pending approval of this run and execute exactly its stored plan.

        The stored plan is re-assessed against current business state first;
        if the decision, the plan or the business snapshot changed, the
        approval expires and nothing executes.
        """
        t = now or datetime.now(UTC)
        run, pending, approval = self._pending_approval(run_id=run_id, approval_id=approval_id)
        plan = pending.plan
        understand_result = pending.understand_result

        act = self._assess(
            semantic_state=understand_result.semantic_state, run=run, is_approved=True, now=t
        )
        try:
            current_plan = build_plan(
                run_id=run.run_id,
                semantic_state=understand_result.semantic_state,
                business_context=act.context.business_context,
                tax_calculation=act.context.tax_calculation,
            )
            plan_problem = None
        except PlanningError as exc:
            current_plan = None
            plan_problem = str(exc)

        stale_reason = None
        if not (act.decision.decision is DecisionType.EXECUTE and act.decision.allowed):
            stale_reason = f"re-validation no longer permits execution ({act.decision.reason})"
        elif current_plan is None:
            stale_reason = f"the plan can no longer be built ({plan_problem})"
        elif current_plan.fingerprint != plan.fingerprint:
            stale_reason = "the execution plan changed since approval was requested"
        elif current_plan.snapshot_version != approval.snapshot_version:
            stale_reason = "business state changed since approval was requested"

        if stale_reason is not None:
            approval.status = ApprovalStatus.EXPIRED
            approval.resolved_at = t
            self.repositories.approvals.save(approval=approval)
            run.failure_code = "APPROVAL_EXPIRED"
            run.failure_message = f"Approval expired: {stale_reason}. Nothing was executed."
            self._set_status(run, VoiceRunStatus.FAILED, t)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.FAILED,
                error_code="APPROVAL_EXPIRED",
                error_message=run.failure_message,
                timestamp=t,
            )
            return self._result(
                run,
                understand_result,
                act=act,
                approval=approval,
                plan=plan,
                message=run.failure_message,
            )

        approval = self.approval_service.approve(
            approval_id=approval.approval_id,
            approved_by=approved_by,
            current_snapshot_version=plan.snapshot_version,
            now=t,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.APPROVED,
            output_summary=f"Approval {approval.approval_id} approved for plan {plan.plan_id}",
            timestamp=t,
        )
        self._set_status(run, VoiceRunStatus.EXECUTING, t)
        return self._execute_plan(
            run,
            understand_result,
            act=act,
            plan=plan,
            approval=approval,
            simulated_faults=simulated_faults or {},
            now=t,
        )

    def reject(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        rejected_by: UUID,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """Reject a pending approval of this run. Its plan can never execute."""
        t = now or datetime.now(UTC)
        run, pending, approval = self._pending_approval(run_id=run_id, approval_id=approval_id)
        approval = self.approval_service.reject(
            approval_id=approval.approval_id, rejected_by=rejected_by, now=t
        )
        run.failure_code = "APPROVAL_REJECTED"
        run.failure_message = "The owner rejected the planned actions. Nothing was executed."
        self._set_status(run, VoiceRunStatus.BLOCKED, t)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.REJECTED,
            output_summary=f"Approval {approval.approval_id} rejected; plan {pending.plan.plan_id} discarded",
            timestamp=t,
        )
        return self._result(
            run,
            pending.understand_result,
            approval=approval,
            plan=pending.plan,
            message=run.failure_message,
        )

    def _pending_approval(
        self, *, run_id: UUID, approval_id: UUID
    ) -> tuple[VoiceRun, PendingExecution, Approval]:
        run = self.repositories.runs.get_by_id(run_id=run_id)
        if run is None:
            raise ApprovalFlowError("RUN_NOT_FOUND", f"Run {run_id} not found.")
        pending = self.repositories.pending_executions.get_by_approval_id(approval_id=approval_id)
        approval = self.repositories.approvals.get_by_id(approval_id=approval_id)
        if pending is None or approval is None:
            raise ApprovalFlowError("APPROVAL_NOT_FOUND", f"Approval {approval_id} not found.")
        if pending.plan.run_id != run.run_id:
            raise ApprovalFlowError(
                "APPROVAL_RUN_MISMATCH", f"Approval {approval_id} does not belong to run {run_id}."
            )
        if approval.status is not ApprovalStatus.REQUESTED:
            raise ApprovalFlowError(
                "APPROVAL_NOT_PENDING",
                f"Approval {approval_id} is {approval.status.value}, not pending.",
            )
        return run, pending, approval

    # ------------------------------------------------------------------ #
    # Execution of an approved plan
    # ------------------------------------------------------------------ #

    def _execute_plan(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        act: _ActAssessment,
        plan: ExecutionPlan,
        approval: Approval,
        simulated_faults: dict[str, Any],
        now: datetime,
    ) -> WorkflowResult:
        executed: list[str] = []
        order_id: str | None = None
        outcome: ExecutionOutcome | None = None

        for call in plan.tool_calls:
            arguments = dict(call.arguments)
            if call.depends_on_order:
                arguments["order_id"] = order_id
            expected_state = None
            entity_type = _EXPECTED_STATE_ENTITY.get(call.tool_name)
            if call.tool_name == "dispatch_order":
                expected_state = {
                    "status": "DISPATCHED",
                    "warehouse_id": arguments["warehouse_id"],
                }

            outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name=call.tool_name,
                arguments=arguments,
                idempotency_key=f"run-{run.run_id}:plan-{plan.plan_id}:{call.tool_name}",
                decision=act.decision,
                approval=approval,
                current_snapshot_version=plan.snapshot_version,
                expected_state=expected_state,
                entity_type=entity_type,
                metadata={
                    "simulate_invoice_failure": bool(
                        simulated_faults.get("simulate_invoice_failure")
                    ),
                    "simulate_dispatch_failure": bool(
                        simulated_faults.get("simulate_dispatch_failure")
                    ),
                },
                now=now,
            )

            if not outcome.success:
                run.failure_code = outcome.tool_result.error_code
                run.failure_message = outcome.message
                self._set_status(run, VoiceRunStatus.FAILED, now)
                self.trace_service.record_stage(
                    run_id=run.run_id,
                    stage=TraceStage.FAILED,
                    tool_name=call.tool_name,
                    error_code=outcome.tool_result.error_code,
                    error_message=outcome.message,
                    timestamp=now,
                )
                done = f" Completed before the failure: {', '.join(executed)}." if executed else ""
                return self._result(
                    run,
                    understand_result,
                    act=act,
                    approval=approval,
                    plan=plan,
                    outcome=outcome,
                    executed=executed,
                    message=outcome.message + done,
                )

            executed.append(call.tool_name)
            if call.tool_name == "create_order":
                order_id = outcome.tool_result.data["order_id"]

        summary = f"Executed approved plan: {', '.join(executed)}."
        if plan.unsupported_actions:
            unsupported = ", ".join(a.value for a in plan.unsupported_actions)
            handoff_case = self.handoff_service.create_case(
                run_id=run.run_id,
                reason=f"Requested actions not supported by the system: {unsupported}.",
                original_request=understand_result.transcript.text,
                blocked_actions=[a.value for a in plan.unsupported_actions],
                attempted_actions=executed,
                recommended_action=f"Perform manually: {unsupported}.",
                now=now,
            )
            self._set_status(run, VoiceRunStatus.HANDOFF, now)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.HANDOFF_CREATED,
                output_summary=f"{summary} Unsupported actions handed off: {unsupported}",
                timestamp=now,
            )
            return self._result(
                run,
                understand_result,
                act=act,
                approval=approval,
                plan=plan,
                outcome=outcome,
                executed=executed,
                handoff_case=handoff_case,
                message=f"{summary} Not performed (unsupported, handed to operator): {unsupported}.",
            )

        self._set_status(run, VoiceRunStatus.COMPLETED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.COMPLETED,
            output_summary=summary,
            timestamp=now,
        )
        return self._result(
            run,
            understand_result,
            act=act,
            approval=approval,
            plan=plan,
            outcome=outcome,
            executed=executed,
            message=summary,
        )

    def _finish_without_writes(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        act: _ActAssessment,
        plan: ExecutionPlan,
        now: datetime,
    ) -> WorkflowResult:
        context = act.context.business_context
        answers: list[str] = []
        for action in plan.read_actions:
            if action.value == "CHECK_PRICE" and context.resolved_price is not None:
                price = context.resolved_price
                answers.append(f"Price: {price.unit_price} {price.currency}/{price.unit}")
            if action.value == "CHECK_INVENTORY":
                for product in context.products:
                    net = sum(
                        i.inventory.available_quantity - i.inventory.reserved_quantity
                        for i in context.inventory
                        if i.inventory.product_id == product.product.product_id
                    )
                    answers.append(f"Stock {product.product.sku}: {net} sellable")
        answer = "; ".join(answers) or "No matching business facts."

        if plan.unsupported_actions:
            unsupported = ", ".join(a.value for a in plan.unsupported_actions)
            handoff_case = self.handoff_service.create_case(
                run_id=run.run_id,
                reason=f"Requested actions not supported by the system: {unsupported}.",
                original_request=understand_result.transcript.text,
                blocked_actions=[a.value for a in plan.unsupported_actions],
                recommended_action=f"Perform manually: {unsupported}.",
                now=now,
            )
            self._set_status(run, VoiceRunStatus.HANDOFF, now)
            return self._result(
                run,
                understand_result,
                act=act,
                plan=plan,
                handoff_case=handoff_case,
                message=f"{answer}. Not performed (unsupported, handed to operator): {unsupported}.",
            )

        self._set_status(run, VoiceRunStatus.COMPLETED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.COMPLETED,
            output_summary=f"Read-only answer: {answer}",
            timestamp=now,
        )
        return self._result(
            run, understand_result, act=act, plan=plan, message=f"Read-only answer: {answer}"
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _understand(self, *, text: str, run: VoiceRun, now: datetime) -> UnderstandResult:
        transcript = Transcript(
            transcript_id=uuid4(),
            provider="test",
            language="hi-en",
            text=text,
            created_at=now,
        )
        run.transcript_id = transcript.transcript_id
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.TRANSCRIBED,
            input_ref=f"text:{text[:60]}",
            output_summary=transcript.text,
            confidence=0.98,
            timestamp=now,
        )
        semantic_state = self.compiler.compile(transcript, run_id=run.run_id)
        evaluation = self.evaluator.evaluate(semantic_state, transcript=transcript)
        understand_result = UnderstandResult(
            result_id=uuid4(),
            run_id=run.run_id,
            transcript=transcript,
            semantic_state=semantic_state,
            evaluation=evaluation,
            created_at=now,
        )
        run.semantic_state_id = semantic_state.semantic_state_id
        self._set_status(run, VoiceRunStatus.SEMANTIC_READY, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.SEMANTIC_COMPILED,
            output_summary=(
                f"Intent={semantic_state.intent.value}, "
                f"requested={[a.action_type.value for a in semantic_state.requested_actions]}, "
                f"negated={[a.action_type.value for a in semantic_state.negated_actions]}"
            ),
            confidence=float(semantic_state.intent_confidence.score),
            timestamp=now,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.INPUT_EVALUATED,
            output_summary=(
                f"Actionability={evaluation.actionability.value}, "
                f"reasons={[r.code.value for r in evaluation.reasons]}"
            ),
            timestamp=now,
        )
        return understand_result

    @staticmethod
    def _unresolvable_partial_references(understand_result: UnderstandResult) -> list[str]:
        """PARTIAL references ACT cannot ground (e.g. 'that order', 'same customer', 'it')."""
        evaluation = understand_result.evaluation
        if evaluation.actionability is not Actionability.PARTIAL:
            return []
        references = {r.reference_id: r for r in understand_result.semantic_state.references}
        problems: list[str] = []
        for reason in evaluation.reasons:
            if reason.effect is not Actionability.PARTIAL:
                continue
            if reason.code is EvaluationReasonCode.TARGET_ORDER_UNRESOLVED:
                problems.append("existing order to modify")
                continue
            for related in reason.related_ids:
                reference = references.get(related)
                if reference and reference.reference_type not in _RESOLVABLE_REFERENCES:
                    problems.append(
                        f"'{reference.surface_text}' ({reference.reference_type.value})"
                    )
        return problems

    def _assess(
        self,
        *,
        semantic_state: SemanticState,
        run: VoiceRun,
        is_approved: bool,
        now: datetime,
    ) -> _ActAssessment:
        context = self.context_resolver.resolve(
            semantic_state=semantic_state, run_id=run.run_id, run_timestamp=now
        )
        snapshot_version = business_snapshot_version(
            context.business_context, context.tax_calculation
        )
        self._set_status(run, VoiceRunStatus.CONTEXT_READY, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.CONTEXT_RESOLVED,
            output_summary=f"Snapshot={snapshot_version}",
            metadata={"snapshot_version": snapshot_version},
            timestamp=now,
        )
        validation = self.validation_engine.validate(
            semantic_state=semantic_state,
            business_context=context.business_context,
            tax_calculation=context.tax_calculation,
            run_id=run.run_id,
            validated_at=now,
        )
        self._set_status(run, VoiceRunStatus.VALIDATED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.VALIDATED,
            output_summary=f"Status={validation.status.value}, checks={len(validation.checks)}",
            timestamp=now,
        )
        risk = self.risk_assessor.assess(
            semantic_state=semantic_state,
            validation_result=validation,
            business_context=context.business_context,
            run_id=run.run_id,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.RISK_ASSESSED,
            output_summary=f"Level={risk.level.value}, score={risk.score:.2f}",
            confidence=risk.score,
            timestamp=now,
        )
        decision = self.policy_engine.evaluate(
            validation_result=validation,
            risk_assessment=risk,
            semantic_state=semantic_state,
            business_context=context.business_context,
            is_approved=is_approved,
            run_id=run.run_id,
        )
        self._set_status(run, VoiceRunStatus.DECIDED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.DECISION_MADE,
            decision=decision.decision.value,
            output_summary=decision.reason,
            timestamp=now,
        )
        return _ActAssessment(context, validation, risk, decision, snapshot_version)

    def _clarify(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        code: DecisionReasonCode,
        reason: str,
        now: datetime,
        act: _ActAssessment | None = None,
        plan: ExecutionPlan | None = None,
    ) -> WorkflowResult:
        decision = Decision(
            decision_id=uuid4(),
            run_id=run.run_id,
            decision=DecisionType.CLARIFY,
            reason_code=code,
            reason=reason,
            allowed=False,
            policy_version=PolicyEngine.VERSION,
        )
        self._set_status(run, VoiceRunStatus.CLARIFICATION_REQUIRED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.DECISION_MADE,
            decision=DecisionType.CLARIFY.value,
            output_summary=reason,
            timestamp=now,
        )
        return self._result(
            run, understand_result, act=act, decision=decision, plan=plan, message=reason
        )

    def _block(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        act: _ActAssessment,
        code: str,
        reason: str,
        now: datetime,
    ) -> WorkflowResult:
        run.failure_code = code
        run.failure_message = reason
        self._set_status(run, VoiceRunStatus.BLOCKED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.BLOCKED,
            error_code=code,
            error_message=reason,
            timestamp=now,
        )
        decision = act.decision
        if decision.decision is not DecisionType.BLOCKED:
            decision = Decision(
                decision_id=uuid4(),
                run_id=run.run_id,
                decision=DecisionType.BLOCKED,
                reason_code=DecisionReasonCode.MISSING_INFORMATION,
                reason=reason,
                allowed=False,
                policy_version=PolicyEngine.VERSION,
            )
        return self._result(
            run,
            understand_result,
            act=act,
            decision=decision,
            message=f"Action blocked: {reason}",
        )

    def _set_status(self, run: VoiceRun, status: VoiceRunStatus, now: datetime) -> None:
        run.status = status
        run.updated_at = now
        self.repositories.runs.save(run=run)

    @staticmethod
    def _result(
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        message: str,
        act: _ActAssessment | None = None,
        decision: Decision | None = None,
        approval: Approval | None = None,
        handoff_case: HandoffCase | None = None,
        plan: ExecutionPlan | None = None,
        outcome: ExecutionOutcome | None = None,
        executed: list[str] | None = None,
    ) -> WorkflowResult:
        return WorkflowResult(
            run=run,
            understand_result=understand_result,
            business_context=act.context.business_context if act else None,
            validation_result=act.validation if act else None,
            risk_assessment=act.risk if act else None,
            decision=decision or (act.decision if act else None),
            approval=approval,
            handoff_case=handoff_case,
            execution_outcome=outcome,
            message=message,
            snapshot_version=plan.snapshot_version if plan else None,
            plan=plan,
            executed_tools=executed or [],
        )

    # ------------------------------------------------------------------ #
    # Audio entry (unchanged behaviour; integration is a later phase)
    # ------------------------------------------------------------------ #

    def process_audio_artifact(
        self,
        *,
        artifact: AudioArtifact,
        run_id: UUID | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """Process an audio artifact by running preprocessor + ASR then delegating to pipeline."""
        t = now or datetime.now(UTC)
        run = self.start_run(run_id=run_id, now=t)
        run.audio_artifact_id = artifact.artifact_id

        if not self.preprocess_audio_service or not self.transcribe_audio_service:
            raise RuntimeError("Audio services not configured on orchestrator.")

        processed = self.preprocess_audio_service.execute(
            request=AudioPreprocessingInput(
                artifact_id=artifact.artifact_id,
                storage_ref=artifact.storage_ref,
                metadata=artifact.metadata,
            )
        )
        transcript = self.transcribe_audio_service.execute(
            request=ASRInput(
                artifact_id=processed.artifact_id,
                storage_ref=processed.storage_ref,
                metadata=processed.metadata,
            )
        )

        return self.process_text(text=transcript.text, run_id=run.run_id, now=t)
