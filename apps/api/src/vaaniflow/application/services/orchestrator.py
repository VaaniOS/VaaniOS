from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.schemas.audio_preprocessing import AudioPreprocessingInput
from vaaniflow.application.services.clarification_merge import merge_clarification
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.context.service import ContextResolutionOutput, ContextResolutionService
from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.followup import (
    ClarificationRecord,
    ClarificationStatus,
    ConfirmationStatus,
    PendingConfirmation,
)
from vaaniflow.domain.models.handoff import HandoffCase
from vaaniflow.domain.models.principal import (
    AuthorizationError,
    Permission,
    Principal,
    Role,
    require_permission,
)
from vaaniflow.domain.models.tax import TaxCalculation
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.validation import ValidationResult, ValidationStatus
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus
from vaaniflow.domain.policies.decision import Decision, DecisionReasonCode, DecisionType
from vaaniflow.domain.policies.risk import RiskAssessment
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.audio import AudioMetadata
from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.semantic import ReferenceType, SemanticState
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import EvaluationReasonCode, UnderstandResult
from vaaniflow.execution.approval import ApprovalService
from vaaniflow.execution.duplicates import DuplicateCheck, DuplicateStatus, check_duplicate_order
from vaaniflow.execution.plan import (
    ExecutionPlan,
    PendingExecution,
    PlanningError,
    StepOutcome,
    StepStatus,
    build_plan,
    business_snapshot_version,
    expected_state_for,
)
from vaaniflow.execution.service import (
    ExecutionOutcome,
    ExecutionService,
    OperatorResolutionError,
)
from vaaniflow.handoff.service import HandoffService, interpret_semantic_state
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.policy.confirmation import ReplyIntent, classify_reply
from vaaniflow.policy.engine import PolicyEngine, confirmable_warnings, warning_key
from vaaniflow.policy.risk import RiskAssessor
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.semantic.evaluation import InputEvaluator
from vaaniflow.traces.models import TraceStage
from vaaniflow.traces.service import TraceService
from vaaniflow.validation.engine import ValidationEngine

# PARTIAL references ACT can ground against business records (historical quotes).
_RESOLVABLE_REFERENCES = frozenset({ReferenceType.HISTORICAL_PRICE, ReferenceType.HISTORICAL_QUOTE})

# Result key identifying the business record each write tool creates.
_ENTITY_ID_KEY = {
    "create_order": "order_id",
    "create_invoice_draft": "invoice_id",
    "dispatch_order": "dispatch_id",
}


class ApprovalFlowError(Exception):
    """An approval/rejection request does not refer to a pending approval of this run."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConfirmationFlowError(ApprovalFlowError):
    """A confirmation reply does not refer to a pending confirmation of this run."""


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
    # Per-tool outcomes of an executed plan (VERIFIED / FAILED / UNKNOWN / NOT_ATTEMPTED).
    step_outcomes: list[StepOutcome] = field(default_factory=list)
    # Earlier pending approvals of this run that this instruction superseded.
    superseded_approval_ids: list[UUID] = field(default_factory=list)
    superseded_confirmation_ids: list[UUID] = field(default_factory=list)
    superseded_clarification_ids: list[UUID] = field(default_factory=list)
    # Follow-up records the next turn or an operator continues from (P2-C, P2-J).
    confirmation: PendingConfirmation | None = None
    clarification: ClarificationRecord | None = None
    duplicate_check: DuplicateCheck | None = None
    # The tax calculation the business rules produced for this assessment, if any.
    tax_calculation: TaxCalculation | None = None

    @property
    def all_steps_verified(self) -> bool | None:
        if not self.step_outcomes:
            return None
        return all(step.status is StepStatus.VERIFIED for step in self.step_outcomes)


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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repositories = repositories
        # Business clock; injectable so validity windows are testable deterministically.
        self.clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
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

    def start_run(
        self,
        *,
        run_id: UUID | None = None,
        owner_id: UUID | None = None,
        now: datetime | None = None,
    ) -> VoiceRun:
        """Create and persist a new VoiceRun aggregate."""
        t = now or self.clock()
        run = VoiceRun(
            run_id=run_id or uuid4(),
            owner_id=owner_id,
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
        t = now or self.clock()
        transcript = Transcript(
            transcript_id=uuid4(),
            provider="text",
            language="hi-en",
            text=text,
            created_at=t,
        )
        return self.process_transcript(transcript=transcript, run_id=run_id, now=t)

    def process_transcript(
        self,
        *,
        transcript: Transcript,
        run_id: UUID | None = None,
        now: datetime | None = None,
        semantic_state: SemanticState | None = None,
        trace_note: str | None = None,
        audio: AudioMetadata | None = None,
    ) -> WorkflowResult:
        """
        Process one instruction transcript (typed text, ASR output, or a merged
        clarification) through UNDERSTAND and ACT. Never executes a write.
        ``semantic_state`` is given only for a merged clarification (ADR-023).
        """
        t = now or self.clock()
        run = self.repositories.runs.get_by_id(run_id=run_id) if run_id else None
        if run is None:
            run = self.start_run(run_id=run_id, now=t)
        self._set_status(run, VoiceRunStatus.PROCESSING, t)

        # 0. A new instruction on this run replaces any plan still awaiting
        #    approval, any confirmation still awaiting a reply and any open
        #    clarification: at most one executable REQUESTED approval per run.
        superseded = self._supersede_pending_approvals(run, now=t)
        superseded_confirmations = self._supersede_pending_confirmations(run, now=t)
        superseded_clarifications = self._supersede_open_clarifications(run, now=t)

        understand_result = self._understand(
            transcript=transcript,
            run=run,
            now=t,
            semantic_state=semantic_state,
            trace_note=trace_note,
            audio=audio,
        )
        result = self._proceed(run, understand_result, now=t)
        result.superseded_approval_ids = superseded
        result.superseded_confirmation_ids = superseded_confirmations
        result.superseded_clarification_ids = superseded_clarifications
        self._link_supersessions(result)
        return result

    def _link_supersessions(self, result: WorkflowResult) -> None:
        """Record on each superseded follow-up what replaced it (P2-B audit)."""
        new_approval = result.approval.approval_id if result.approval else None
        for approval_id in result.superseded_approval_ids:
            approval = self.repositories.approvals.get_by_id(approval_id=approval_id)
            if approval is not None and new_approval is not None:
                approval.superseded_by = new_approval
                self.repositories.approvals.save(approval=approval)
        new_confirmation = result.confirmation.confirmation_id if result.confirmation else None
        for confirmation_id in result.superseded_confirmation_ids:
            confirmation = self.repositories.pending_confirmations.get_by_id(
                confirmation_id=confirmation_id
            )
            if confirmation is not None and new_confirmation is not None:
                confirmation.superseded_by = new_confirmation
                self.repositories.pending_confirmations.save(confirmation=confirmation)
        transcript_id = (
            result.understand_result.transcript.transcript_id if result.understand_result else None
        )
        for clarification_id in result.superseded_clarification_ids:
            clarification = self.repositories.clarifications.get_by_id(
                clarification_id=clarification_id
            )
            if clarification is not None:
                clarification.superseded_by_transcript_id = transcript_id
                self.repositories.clarifications.save(clarification=clarification)

    def clarify(self, *, run_id: UUID, reply: str, now: datetime | None = None) -> WorkflowResult:
        """
        Answer the run's open clarification (ADR-023). A short reply is merged
        into exactly the slots that were asked for and the merged request goes
        through the full ACT pipeline; a reply naming actions is a new
        instruction; a reply that answers nothing asked, or contradicts what was
        understood, changes nothing. Callers authorize the principal first.
        """
        t = now or self.clock()
        run = self.repositories.runs.get_by_id(run_id=run_id)
        if run is None:
            raise ApprovalFlowError("RUN_NOT_FOUND", f"Run {run_id} not found.")
        open_clarifications = [
            c
            for c in self.repositories.clarifications.list_by_run(run_id=run.run_id)
            if c.status is ClarificationStatus.OPEN
        ]
        if not open_clarifications:
            return self.process_text(text=reply, run_id=run.run_id, now=t)
        clarification = open_clarifications[-1]
        outcome = merge_clarification(clarification, reply, compiler=self.compiler, now=t)
        if outcome.kind == "instruction":
            return self.process_text(text=reply, run_id=run.run_id, now=t)
        if outcome.kind == "refused":
            result = self._result(run, clarification.understand_result, message=outcome.message)
            result.clarification = clarification
            return result
        assert outcome.transcript is not None and outcome.semantic_state is not None
        return self.process_transcript(
            transcript=outcome.transcript,
            run_id=run.run_id,
            now=t,
            semantic_state=outcome.semantic_state,
            trace_note=(
                f"clarification {clarification.clarification_id} merged into "
                f"{[s.value for s in outcome.filled_slots]}"
            ),
        )

    def _proceed(
        self, run: VoiceRun, understand_result: UnderstandResult, *, now: datetime
    ) -> WorkflowResult:
        t = now
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

        return self._act(run, understand_result, now=t)

    def _act(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        now: datetime,
        utterance_time: datetime | None = None,
        confirmed_warning_keys: frozenset[str] = frozenset(),
    ) -> WorkflowResult:
        """
        ACT for an UnderstandResult that passed the UNDERSTAND gates: context,
        validation, risk, policy, plan, duplicate check, approval request.

        Never executes a write. ``confirmed_warning_keys`` are the validation
        warnings the user explicitly confirmed (P2-C); approval is still required.
        """
        t = now
        semantic_state = understand_result.semantic_state
        evaluation = understand_result.evaluation

        # 3–6. Context → validation → risk → policy
        act = self._assess(
            semantic_state=semantic_state,
            run=run,
            is_approved=False,
            now=t,
            utterance_time=utterance_time,
            confirmed_warning_keys=confirmed_warning_keys,
        )
        decision = act.decision

        if decision.decision is DecisionType.CLARIFY:
            return self._clarify(
                run,
                understand_result,
                code=decision.reason_code,
                reason=decision.reason,
                act=act,
                now=t,
            )

        if decision.decision is DecisionType.CONFIRM:
            return self._request_confirmation(run, understand_result, act=act, now=t)

        if decision.decision is DecisionType.HUMAN_HANDOFF:
            self._set_status(run, VoiceRunStatus.HANDOFF, t)
            handoff_case = self.handoff_service.create_case_from_evaluation(
                run_id=run.run_id,
                original_request=understand_result.transcript.text,
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

        # 7b. A business-level duplicate of an existing order is never re-created.
        duplicate = check_duplicate_order(plan=plan, repositories=self.repositories, now=t)
        self._trace_duplicate_check(run, duplicate, plan, now=t)
        if duplicate.status is not DuplicateStatus.NO_DUPLICATE:
            return self._refuse_duplicate(
                run, understand_result, act=act, plan=plan, duplicate=duplicate, now=t
            )

        # 8. Business writes always require an approval bound to this exact plan.
        #    The request comes from the system; no requester identity is invented.
        approval = self.approval_service.request_approval(
            run_id=run.run_id,
            snapshot_version=plan.snapshot_version,
            plan_id=plan.plan_id,
            plan_fingerprint=plan.fingerprint,
            requested_by=run.owner_id,
            now=t,
        )
        self.repositories.pending_executions.save(
            pending=PendingExecution(
                approval_id=approval.approval_id,
                plan=plan,
                understand_result=understand_result,
                created_at=t,
                context_snapshot=act.context.snapshot,
                validation_result=act.validation,
                decision_reason=decision.reason,
                confirmed_warning_keys=sorted(confirmed_warning_keys),
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
            message=f"Approval required for planned actions: {', '.join(plan.tool_names)}. "
            "Nothing has been executed." + unsupported,
            snapshot_version=plan.snapshot_version,
            plan=plan,
            duplicate_check=duplicate,
            tax_calculation=act.context.tax_calculation,
        )

    # ------------------------------------------------------------------ #
    # Approval
    # ------------------------------------------------------------------ #

    def approve(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        actor: Principal | None = None,
        simulated_faults: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Approve a pending approval of this run and execute exactly its stored plan.

        Requires a principal holding APPROVE (OWNER); the recorded approver is
        that principal, never an identity from a request (ADR-022). The stored
        plan is re-assessed against current business state first; if the
        decision, the plan or the business snapshot changed, the approval
        expires and nothing executes.
        """
        t = now or self.clock()
        actor = self._authorize(actor, Permission.APPROVE)
        run, pending, approval = self._pending_approval(run_id=run_id, approval_id=approval_id)
        plan = pending.plan
        understand_result = pending.understand_result

        act = self._assess(
            semantic_state=understand_result.semantic_state,
            run=run,
            is_approved=True,
            now=t,
            utterance_time=understand_result.transcript.created_at,
            confirmed_warning_keys=frozenset(pending.confirmed_warning_keys),
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

        # Duplicate check again at the execution boundary: another run may have
        # created the equivalent order after this approval was requested.
        duplicate: DuplicateCheck | None = None
        if stale_reason is None:
            duplicate = check_duplicate_order(plan=plan, repositories=self.repositories, now=t)
            self._trace_duplicate_check(run, duplicate, plan, now=t)
            if duplicate.status is not DuplicateStatus.NO_DUPLICATE:
                approval = self.approval_service.expire(
                    approval_id=approval.approval_id,
                    reason=duplicate.reason,
                    observed_snapshot_version=act.snapshot_version,
                    now=t,
                )
                return self._refuse_duplicate(
                    run,
                    understand_result,
                    act=act,
                    plan=plan,
                    duplicate=duplicate,
                    approval=approval,
                    now=t,
                )

        if stale_reason is not None:
            approval = self.approval_service.expire(
                approval_id=approval.approval_id,
                reason=stale_reason,
                observed_snapshot_version=act.snapshot_version,
                now=t,
            )
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

        # The snapshot recomputed now (equal to the plan's, or it would have expired).
        approval = self.approval_service.approve(
            approval_id=approval.approval_id,
            actor=actor,
            current_snapshot_version=act.snapshot_version,
            now=t,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.APPROVED,
            output_summary=f"Approval {approval.approval_id} approved for plan {plan.plan_id}",
            timestamp=t,
        )
        self._set_status(run, VoiceRunStatus.EXECUTING, t)
        result = self._execute_plan(
            run,
            understand_result,
            act=act,
            plan=plan,
            approval=approval,
            simulated_faults=simulated_faults or {},
            now=t,
        )
        result.duplicate_check = duplicate
        self._link_approval_records(approval, result.step_outcomes)
        return result

    def _link_approval_records(self, approval: Approval, steps: list[StepOutcome]) -> None:
        """Point the approval at the verified business records its plan produced."""
        fields = {
            "create_order": "order_id",
            "create_invoice_draft": "invoice_id",
            "dispatch_order": "dispatch_id",
        }
        for step in steps:
            name = fields.get(step.tool_name)
            if name and step.status is StepStatus.VERIFIED and step.entity_id:
                setattr(approval, name, UUID(step.entity_id))
        self.repositories.approvals.save(approval=approval)

    def reject(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        actor: Principal | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """Reject a pending approval of this run (APPROVE permission). Its plan never executes."""
        t = now or self.clock()
        actor = self._authorize(actor, Permission.APPROVE)
        run, pending, approval = self._pending_approval(run_id=run_id, approval_id=approval_id)
        approval = self.approval_service.reject(
            approval_id=approval.approval_id, actor=actor, reason=reason, now=t
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

    # ------------------------------------------------------------------ #
    # Confirmation (P2-C)
    # ------------------------------------------------------------------ #

    def confirm(
        self,
        *,
        run_id: UUID,
        reply: str,
        confirmation_id: UUID | None = None,
        actor: Principal | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Answer the confirmation pending on this run.

        A reply only ever answers a confirmation of *this* run that is still
        REQUESTED. "Yes" accepts exactly the warnings it was asked about, on the
        business snapshot it was asked with; if the facts changed it expires.
        Confirmation never executes anything: writes still need approval.
        Requires CONFIRM; a REQUESTER may only answer for a run they own.
        """
        t = now or self.clock()
        actor = self._authorize(actor, Permission.CONFIRM, error=ConfirmationFlowError)
        run = self.repositories.runs.get_by_id(run_id=run_id)
        if run is None:
            raise ConfirmationFlowError("RUN_NOT_FOUND", f"Run {run_id} not found.")
        if (
            run.owner_id is not None
            and run.owner_id != actor.principal_id
            and not actor.has_role(Role.OWNER)
        ):
            raise ConfirmationFlowError(
                "FORBIDDEN", f"Run {run_id} belongs to another principal; only it may confirm."
            )
        confirmation = self._pending_confirmation(run, confirmation_id)
        if confirmation is None:
            return WorkflowResult(
                run=run,
                understand_result=None,
                business_context=None,
                validation_result=None,
                risk_assessment=None,
                decision=Decision(
                    decision_id=uuid4(),
                    run_id=run.run_id,
                    decision=DecisionType.CLARIFY,
                    reason_code=DecisionReasonCode.MISSING_INFORMATION,
                    reason="Nothing on this run is awaiting confirmation.",
                    allowed=False,
                    policy_version=PolicyEngine.VERSION,
                ),
                approval=None,
                handoff_case=None,
                execution_outcome=None,
                message="Nothing on this run is awaiting confirmation; nothing was changed.",
            )

        understand_result = confirmation.understand_result
        intent = classify_reply(reply)
        if intent is ReplyIntent.UNCLEAR:
            result = self._result(
                run,
                understand_result,
                decision=Decision(
                    decision_id=uuid4(),
                    run_id=run.run_id,
                    decision=DecisionType.CLARIFY,
                    reason_code=DecisionReasonCode.AMBIGUOUS_INPUT,
                    reason="The reply was not a clear yes or no.",
                    allowed=False,
                    policy_version=PolicyEngine.VERSION,
                ),
                message=(
                    f"The reply was not understood as yes or no; confirmation "
                    f"{confirmation.confirmation_id} is still pending. Nothing was changed."
                ),
            )
            result.confirmation = confirmation
            return result

        confirmation.reply_text = reply
        confirmation.confirmed_by = actor.principal_id
        confirmation.confirmed_actor = actor
        confirmation.resolved_at = t
        if intent is ReplyIntent.DECLINE:
            confirmation.status = ConfirmationStatus.DECLINED
            confirmation.resolution_reason = "The user declined."
            self.repositories.pending_confirmations.save(confirmation=confirmation)
            run.failure_code = "CONFIRMATION_DECLINED"
            run.failure_message = "Not confirmed. Nothing was planned or executed."
            self._set_status(run, VoiceRunStatus.BLOCKED, t)
            self._trace_confirmation(run, confirmation, now=t)
            result = self._result(run, understand_result, message=run.failure_message)
            result.confirmation = confirmation
            return result

        utterance_time = understand_result.transcript.created_at
        current = self._assess(
            semantic_state=understand_result.semantic_state,
            run=run,
            is_approved=False,
            now=t,
            utterance_time=utterance_time,
            confirmed_warning_keys=frozenset(confirmation.warning_keys),
        )
        if current.snapshot_version != confirmation.snapshot_version:
            # The user confirmed facts that no longer hold: re-evaluate from scratch.
            confirmation.status = ConfirmationStatus.EXPIRED
            confirmation.resolution_reason = (
                "Business state changed after the confirmation was requested; "
                "the confirmed interpretation no longer applies."
            )
            self.repositories.pending_confirmations.save(confirmation=confirmation)
            self._trace_confirmation(run, confirmation, now=t)
            result = self._act(run, understand_result, now=t, utterance_time=utterance_time)
            result.superseded_confirmation_ids = [confirmation.confirmation_id]
            result.message = f"{confirmation.resolution_reason} {result.message}"
            return result

        confirmation.status = ConfirmationStatus.CONFIRMED
        confirmation.resolution_reason = "The user confirmed the interpretation."
        self.repositories.pending_confirmations.save(confirmation=confirmation)
        self._trace_confirmation(run, confirmation, now=t)
        return self._act(
            run,
            understand_result,
            now=t,
            utterance_time=utterance_time,
            confirmed_warning_keys=frozenset(confirmation.warning_keys),
        )

    def _pending_confirmation(
        self, run: VoiceRun, confirmation_id: UUID | None
    ) -> PendingConfirmation | None:
        if confirmation_id is None:
            pending = [
                c
                for c in self.repositories.pending_confirmations.list_by_run(run_id=run.run_id)
                if c.status is ConfirmationStatus.REQUESTED
            ]
            return pending[0] if pending else None
        confirmation = self.repositories.pending_confirmations.get_by_id(
            confirmation_id=confirmation_id
        )
        if confirmation is None:
            raise ConfirmationFlowError(
                "CONFIRMATION_NOT_FOUND", f"Confirmation {confirmation_id} not found."
            )
        if confirmation.run_id != run.run_id:
            raise ConfirmationFlowError(
                "CONFIRMATION_RUN_MISMATCH",
                f"Confirmation {confirmation_id} does not belong to run {run.run_id}.",
            )
        if confirmation.status is ConfirmationStatus.SUPERSEDED:
            raise ConfirmationFlowError(
                "CONFIRMATION_SUPERSEDED",
                f"Confirmation {confirmation_id} was superseded by a newer instruction.",
            )
        if confirmation.status is not ConfirmationStatus.REQUESTED:
            raise ConfirmationFlowError(
                "CONFIRMATION_NOT_PENDING",
                f"Confirmation {confirmation_id} is {confirmation.status.value}, not pending.",
            )
        return confirmation

    def _request_confirmation(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        act: _ActAssessment,
        now: datetime,
    ) -> WorkflowResult:
        warnings = confirmable_warnings(act.validation)
        context = act.context.business_context
        state = understand_result.semantic_state
        item = state.items[0] if len(state.items) == 1 else None
        understood = []
        if context.customer:
            understood.append(context.customer.customer.name)
        if item and item.quantity:
            understood.append(f"{item.quantity.value} {item.quantity.unit or ''}".strip())
        if len(context.products) == 1:
            understood.append(context.products[0].product.name)
        if context.resolved_price:
            price = context.resolved_price
            understood.append(f"at the quoted {price.unit_price} {price.currency}/{price.unit}")
        prompt = (
            f"I understood: {' · '.join(understood) or 'the request'}. "
            + " ".join(w.message for w in warnings)
            + " Confirm? (yes/no)"
        )
        confirmation = PendingConfirmation(
            confirmation_id=uuid4(),
            run_id=run.run_id,
            status=ConfirmationStatus.REQUESTED,
            warning_keys=sorted(warning_key(w) for w in warnings),
            warnings=[w.message for w in warnings],
            prompt=prompt,
            snapshot_version=act.snapshot_version,
            understand_result=understand_result,
            created_at=now,
        )
        self.repositories.pending_confirmations.save(confirmation=confirmation)
        self._set_status(run, VoiceRunStatus.CONFIRMATION_REQUIRED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.CONFIRMATION_REQUESTED,
            output_summary=f"Confirmation {confirmation.confirmation_id}: {prompt}",
            timestamp=now,
        )
        result = self._result(
            run,
            understand_result,
            act=act,
            message=(
                f"Confirmation required: {act.decision.reason} {prompt} "
                "Nothing has been planned or executed."
            ),
        )
        result.confirmation = confirmation
        return result

    def _trace_confirmation(
        self, run: VoiceRun, confirmation: PendingConfirmation, *, now: datetime
    ) -> None:
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.CONFIRMATION_RESOLVED,
            output_summary=(
                f"Confirmation {confirmation.confirmation_id} {confirmation.status.value}: "
                f"{confirmation.resolution_reason}"
            ),
            timestamp=now,
        )

    def _supersede_pending_confirmations(self, run: VoiceRun, *, now: datetime) -> list[UUID]:
        superseded: list[UUID] = []
        for confirmation in self.repositories.pending_confirmations.list_by_run(run_id=run.run_id):
            if confirmation.status is not ConfirmationStatus.REQUESTED:
                continue
            confirmation.status = ConfirmationStatus.SUPERSEDED
            confirmation.resolved_at = now
            confirmation.resolution_reason = "Superseded by a new instruction on this run."
            self.repositories.pending_confirmations.save(confirmation=confirmation)
            superseded.append(confirmation.confirmation_id)
            self._trace_confirmation(run, confirmation, now=now)
        return superseded

    def _supersede_open_clarifications(self, run: VoiceRun, *, now: datetime) -> list[UUID]:
        superseded: list[UUID] = []
        for clarification in self.repositories.clarifications.list_by_run(run_id=run.run_id):
            if clarification.status is not ClarificationStatus.OPEN:
                continue
            clarification.status = ClarificationStatus.SUPERSEDED
            clarification.resolved_at = now
            self.repositories.clarifications.save(clarification=clarification)
            superseded.append(clarification.clarification_id)
        return superseded

    # ------------------------------------------------------------------ #
    # Duplicate business orders (P2-A)
    # ------------------------------------------------------------------ #

    def _trace_duplicate_check(
        self, run: VoiceRun, check: DuplicateCheck, plan: ExecutionPlan, *, now: datetime
    ) -> None:
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.DUPLICATE_CHECKED,
            output_summary=f"Plan {plan.plan_id}: {check.status.value} — {check.reason}",
            metadata={
                "duplicate_order_ids": [str(i) for i in check.duplicate_order_ids],
                "business_key": check.business_key,
            },
            timestamp=now,
        )

    def _refuse_duplicate(
        self,
        run: VoiceRun,
        understand_result: UnderstandResult,
        *,
        act: _ActAssessment,
        plan: ExecutionPlan,
        duplicate: DuplicateCheck,
        now: datetime,
        approval: Approval | None = None,
    ) -> WorkflowResult:
        handoff_case: HandoffCase | None = None
        if duplicate.status is DuplicateStatus.DUPLICATE_CHECK_UNAVAILABLE:
            run.failure_code = "DUPLICATE_CHECK_UNAVAILABLE"
            reason = f"Cannot rule out a duplicate order: {duplicate.reason} No order was created."
            decision_type = DecisionType.HUMAN_HANDOFF
            status = VoiceRunStatus.HANDOFF
            handoff_case = self.handoff_service.create_case(
                run_id=run.run_id,
                reason=reason,
                original_request=understand_result.transcript.text,
                interpreted_request=interpret_semantic_state(understand_result.semantic_state),
                blocked_actions=plan.tool_names,
                recommended_action="Check existing orders for this customer before re-approving.",
                now=now,
            )
        else:
            run.failure_code = "DUPLICATE_ORDER"
            reason = (
                f"{duplicate.reason} No new order was created; use the existing order "
                "or cancel it before placing this one again."
            )
            decision_type = DecisionType.BLOCKED
            status = VoiceRunStatus.BLOCKED
        run.failure_message = reason
        self._set_status(run, status, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.BLOCKED
            if decision_type is DecisionType.BLOCKED
            else TraceStage.HANDOFF_CREATED,
            error_code=run.failure_code,
            error_message=reason,
            timestamp=now,
        )
        result = self._result(
            run,
            understand_result,
            act=act,
            decision=Decision(
                decision_id=uuid4(),
                run_id=run.run_id,
                decision=decision_type,
                reason_code=DecisionReasonCode.DUPLICATE_ORDER,
                reason=reason,
                allowed=False,
                requires_human_handoff=decision_type is DecisionType.HUMAN_HANDOFF,
                policy_version=PolicyEngine.VERSION,
            ),
            approval=approval,
            handoff_case=handoff_case,
            plan=plan,
            message=reason,
        )
        result.duplicate_check = duplicate
        return result

    # ------------------------------------------------------------------ #
    # Operator resolution of UNKNOWN (P2-D)
    # ------------------------------------------------------------------ #

    def resolve_unknown(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        attempt: int,
        outcome: ToolExecutionStatus,
        reason: str,
        actor: Principal | None = None,
        entity_id: UUID | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Record an operator's verified resolution of one UNKNOWN execution and
        recompute the run from the plan's step evidence. The UNKNOWN history is
        kept on the execution record; remaining steps are never run here.
        Requires RESOLVE_UNKNOWN (OPERATOR).
        """
        t = now or self.clock()
        actor = self._authorize(actor, Permission.RESOLVE_UNKNOWN, error=OperatorResolutionError)
        run = self.repositories.runs.get_by_id(run_id=run_id)
        if run is None:
            raise OperatorResolutionError("RUN_NOT_FOUND", f"Run {run_id} not found.")
        execution = self.repositories.tool_executions.get_by_id(execution_id=execution_id)
        if execution is None:
            raise OperatorResolutionError(
                "EXECUTION_NOT_FOUND", f"Tool execution {execution_id} not found."
            )
        try:
            expected_state = expected_state_for(execution.tool_name, execution.arguments)
        except PlanningError as exc:
            raise OperatorResolutionError("NO_VERIFICATION_CONTRACT", str(exc)) from exc

        resolved = self.execution_service.resolve_unknown_by_operator(
            run_id=run.run_id,
            execution_id=execution_id,
            attempt=attempt,
            outcome=outcome,
            reason=reason,
            expected_state=expected_state,
            entity_id=entity_id,
            actor=actor,
            now=t,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.OPERATOR_RESOLVED,
            tool_name=execution.tool_name,
            output_summary=(
                f"Execution {execution_id} ({execution.tool_name}, attempt {attempt}) "
                f"UNKNOWN → {resolved.execution.status.value} by operator: {reason}"
            ),
            timestamp=t,
        )

        pending = next(
            (
                p
                for p in self.repositories.pending_executions.list_by_run(run_id=run.run_id)
                if f":plan-{p.plan.plan_id}:" in execution.idempotency_key
            ),
            None,
        )
        if pending is None:
            return self._result(run, None, outcome=resolved, message=resolved.message)

        plan = pending.plan
        steps = self._steps_from_records(run, plan)
        approval = self.repositories.approvals.get_by_id(approval_id=pending.approval_id)
        if approval is not None:
            self._link_approval_records(approval, steps)
        statuses = {step.status for step in steps}
        summary = self._step_summary(steps)
        if StepStatus.UNKNOWN in statuses:
            run.failure_code = "OUTCOME_UNKNOWN"
            status = VoiceRunStatus.HANDOFF
        elif statuses == {StepStatus.VERIFIED}:
            run.failure_code = None
            run.failure_message = None
            status = (
                VoiceRunStatus.HANDOFF if plan.unsupported_actions else VoiceRunStatus.COMPLETED
            )
        elif StepStatus.FAILED in statuses:
            failed = next(s for s in steps if s.status is StepStatus.FAILED)
            run.failure_code = failed.error_code
            status = (
                VoiceRunStatus.PARTIALLY_COMPLETED
                if StepStatus.VERIFIED in statuses
                else VoiceRunStatus.FAILED
            )
        else:
            run.failure_code = "REMAINING_STEPS_NOT_ATTEMPTED"
            status = VoiceRunStatus.HANDOFF
        message = f"{resolved.message} {summary}"
        if status is VoiceRunStatus.HANDOFF and StepStatus.NOT_ATTEMPTED in statuses:
            # There is no plan continuation: re-sending the request would be refused
            # as a duplicate of the verified records, so say what is actually true.
            remaining = ", ".join(
                s.tool_name for s in steps if s.status is StepStatus.NOT_ATTEMPTED
            )
            message += (
                f" Remaining steps ({remaining}) were not attempted and will not run "
                "automatically. The verified records stand; a new request for the same "
                "order would be refused as a duplicate of them, so an operator must "
                "complete the remaining steps manually."
            )
        if run.failure_code:
            run.failure_message = message
        self._set_status(run, status, t)
        return self._result(
            run,
            pending.understand_result,
            approval=approval,
            plan=plan,
            outcome=resolved,
            executed=[s.tool_name for s in steps if s.status is StepStatus.VERIFIED],
            steps=steps,
            message=message,
        )

    def _steps_from_records(self, run: VoiceRun, plan: ExecutionPlan) -> list[StepOutcome]:
        """Per-step outcome of a plan, read from its persisted tool executions."""
        steps: list[StepOutcome] = []
        mapping = {
            ToolExecutionStatus.SUCCEEDED: StepStatus.VERIFIED,
            ToolExecutionStatus.FAILED: StepStatus.FAILED,
            ToolExecutionStatus.UNKNOWN: StepStatus.UNKNOWN,
        }
        for tool_name in plan.tool_names:
            execution = self.repositories.tool_executions.get_by_idempotency_key(
                idempotency_key=f"run-{run.run_id}:plan-{plan.plan_id}:{tool_name}"
            )
            if execution is None or execution.status not in mapping:
                steps.append(
                    StepOutcome(
                        tool_name=tool_name,
                        status=StepStatus.NOT_ATTEMPTED,
                        message="Not attempted.",
                    )
                )
                continue
            verification = self.repositories.verifications.get_by_execution_id(
                execution_id=execution.execution_id
            )
            entity_id = (execution.result or {}).get(_ENTITY_ID_KEY.get(tool_name, ""))
            steps.append(
                StepOutcome(
                    tool_name=tool_name,
                    status=mapping[execution.status],
                    execution_status=execution.status.value,
                    verification_status=verification.status.value if verification else None,
                    entity_id=str(entity_id) if entity_id else None,
                    error_code=execution.error_code,
                    message=execution.resolution_reason
                    or execution.error_message
                    or execution.status.value,
                    reconciled=execution.reconciled,
                )
            )
        return steps

    @staticmethod
    def _authorize(
        actor: Principal | None,
        permission: Permission,
        *,
        error: type[Exception] = ApprovalFlowError,
    ) -> Principal:
        """The actor if it holds ``permission``; otherwise ``error`` with UNAUTHENTICATED/FORBIDDEN."""
        try:
            return require_permission(actor, permission)
        except AuthorizationError as exc:
            raise error(exc.code, exc.message) from exc  # type: ignore[call-arg]

    def escalate(
        self,
        *,
        run_id: UUID,
        reason: str,
        actor: Principal | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """
        Manual escalation to a human operator (CREATE_HANDOFF permission).

        Everything pending on the run is superseded first, so nothing requested
        before the escalation can execute afterwards. The case is assigned to the
        escalating operator and never claims that anything was completed.
        """
        t = now or self.clock()
        actor = self._authorize(actor, Permission.CREATE_HANDOFF)
        run = self.repositories.runs.get_by_id(run_id=run_id)
        if run is None:
            raise ApprovalFlowError("RUN_NOT_FOUND", f"Run {run_id} not found.")
        cause = f"an operator escalation ({actor.display_name})"
        superseded = self._supersede_pending_approvals(run, now=t, cause=cause)
        superseded_confirmations = self._supersede_pending_confirmations(run, now=t)
        self._supersede_open_clarifications(run, now=t)
        instructions = self.repositories.understand_results.list_by_run(run_id=run.run_id)
        latest = instructions[-1] if instructions else None
        executions = self.repositories.tool_executions.list_by_run(run_id=run.run_id)
        case = self.handoff_service.create_case(
            run_id=run.run_id,
            reason=reason,
            original_request=latest.transcript.text
            if latest
            else "(no instruction was recorded on this run)",
            interpreted_request=interpret_semantic_state(latest.semantic_state) if latest else {},
            attempted_actions=[f"{e.tool_name}: {e.status.value}" for e in executions],
            blocked_actions=[f"approval {a}" for a in superseded]
            + [f"confirmation {c}" for c in superseded_confirmations],
            recommended_action="Review the run audit trail before taking any business action.",
            now=t,
        )
        case = self.handoff_service.assign_case(
            handoff_id=case.handoff_id, assigned_to=actor.principal_id
        )
        run.failure_code = "MANUAL_ESCALATION"
        run.failure_message = f"Escalated to a human operator: {reason}"
        self._set_status(run, VoiceRunStatus.HANDOFF, t)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.HANDOFF_CREATED,
            output_summary=(
                f"Manual escalation by {actor.display_name}: handoff {case.handoff_id}; "
                f"superseded approvals={len(superseded)}, "
                f"confirmations={len(superseded_confirmations)}"
            ),
            timestamp=t,
        )
        result = self._result(
            run,
            latest,
            handoff_case=case,
            message=(
                f"Escalated to a human operator (handoff {case.handoff_id}). Nothing pending "
                "on this run can execute."
            ),
        )
        result.superseded_approval_ids = superseded
        result.superseded_confirmation_ids = superseded_confirmations
        return result

    def _supersede_pending_approvals(
        self, run: VoiceRun, *, now: datetime, cause: str = "a new instruction on this run"
    ) -> list[UUID]:
        superseded: list[UUID] = []
        for pending in self.repositories.pending_executions.list_by_run(run_id=run.run_id):
            approval = self.repositories.approvals.get_by_id(approval_id=pending.approval_id)
            if approval is None or approval.status is not ApprovalStatus.REQUESTED:
                continue
            self.approval_service.supersede(approval_id=approval.approval_id, now=now)
            superseded.append(approval.approval_id)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.APPROVAL_SUPERSEDED,
                output_summary=(
                    f"Approval {approval.approval_id} (plan {pending.plan.plan_id}) superseded "
                    f"by {cause}; it can no longer execute."
                ),
                timestamp=now,
            )
        return superseded

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
        if approval.status is ApprovalStatus.SUPERSEDED:
            raise ApprovalFlowError(
                "APPROVAL_SUPERSEDED",
                f"Approval {approval_id} was superseded by a newer instruction on run "
                f"{run_id}. Nothing was executed.",
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
        """
        Execute the approved plan step by step and report each step's evidence.

        A step counts as done only when read-back verified it. The first step
        that does not verify stops the plan; later steps are NOT_ATTEMPTED.
        Nothing is rolled back and no rollback is claimed.
        """
        steps: list[StepOutcome] = []
        executed: list[str] = []
        order_id: str | None = None
        outcome: ExecutionOutcome | None = None
        stopped: StepOutcome | None = None
        metadata = {
            "simulate_invoice_failure": bool(simulated_faults.get("simulate_invoice_failure")),
            "simulate_dispatch_failure": bool(simulated_faults.get("simulate_dispatch_failure")),
            "simulate_timeout": dict(simulated_faults.get("simulate_timeout") or {}),
        }

        for call in plan.tool_calls:
            if stopped is not None:
                steps.append(
                    StepOutcome(
                        tool_name=call.tool_name,
                        status=StepStatus.NOT_ATTEMPTED,
                        message=f"Not attempted: {stopped.tool_name} did not verify.",
                    )
                )
                continue

            arguments = dict(call.arguments)
            if call.depends_on_order:
                arguments["order_id"] = order_id
            try:
                expected_state = expected_state_for(call.tool_name, arguments)
            except PlanningError as exc:
                # No read-back contract (P2-G): the tool is never invoked, so
                # nothing is written and nothing can be falsely reported.
                stopped = StepOutcome(
                    tool_name=call.tool_name,
                    status=StepStatus.FAILED,
                    error_code="NO_VERIFICATION_CONTRACT",
                    message=f"Not executed: {exc}",
                )
                steps.append(stopped)
                continue

            outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name=call.tool_name,
                arguments=arguments,
                idempotency_key=f"run-{run.run_id}:plan-{plan.plan_id}:{call.tool_name}",
                decision=act.decision,
                approval=approval,
                current_snapshot_version=plan.snapshot_version,
                expected_state=expected_state,
                metadata=metadata,
                now=now,
            )
            step = self._step_outcome(call.tool_name, outcome)
            steps.append(step)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.VERIFIED
                if step.status is StepStatus.VERIFIED
                else TraceStage.TOOL_EXECUTED,
                tool_name=call.tool_name,
                output_summary=(
                    f"{call.tool_name}: {step.status.value} "
                    f"(execution={step.execution_status}, verification={step.verification_status})"
                    + (
                        f"; reconciled by read-back after UNKNOWN ({outcome.execution.prior_error_code})"
                        if step.reconciled
                        else ""
                    )
                ),
                error_code=step.error_code,
                timestamp=now,
            )

            if step.status is StepStatus.VERIFIED:
                executed.append(call.tool_name)
                if call.tool_name == "create_order":
                    order_id = outcome.tool_result.data["order_id"]
            else:
                stopped = step

        def result(**kwargs: Any) -> WorkflowResult:
            return self._result(
                run,
                understand_result,
                act=act,
                approval=approval,
                plan=plan,
                outcome=outcome,
                executed=executed,
                steps=steps,
                **kwargs,
            )

        unsupported = ", ".join(a.value for a in plan.unsupported_actions)
        not_performed = (
            f" Not performed (unsupported, handed to operator): {unsupported}."
            if unsupported
            else ""
        )

        interpreted = self._handoff_interpretation(understand_result, plan, approval, steps)

        if stopped is not None:
            summary = self._step_summary(steps)
            unknown = [s for s in steps if s.status is StepStatus.UNKNOWN]
            run.failure_code = stopped.error_code
            run.failure_message = stopped.message

            if unknown:
                # The business state is uncertain: a person must establish it
                # before anything else happens. Nothing is retried or reported done.
                run.failure_code = "OUTCOME_UNKNOWN"
                handoff_case = self.handoff_service.create_case(
                    run_id=run.run_id,
                    reason=(
                        f"Outcome of {', '.join(s.tool_name for s in unknown)} is unknown "
                        "after an uncertain tool response; not retried automatically."
                    ),
                    original_request=understand_result.transcript.text,
                    blocked_actions=[
                        s.tool_name for s in steps if s.status is not StepStatus.VERIFIED
                    ]
                    + [a.value for a in plan.unsupported_actions],
                    attempted_actions=[
                        s.tool_name for s in steps if s.status is not StepStatus.NOT_ATTEMPTED
                    ],
                    recommended_action=(
                        "Check the business system for the unknown operation and resolve it "
                        "(POST /runs/{run_id}/executions/{execution_id}/resolve); do not "
                        "repeat it blindly."
                    ),
                    interpreted_request=interpreted,
                    uncertainties=[f"{s.tool_name}: {s.message}" for s in unknown],
                    evidence=self._step_evidence(steps),
                    now=now,
                )
                self._set_status(run, VoiceRunStatus.HANDOFF, now)
                self.trace_service.record_stage(
                    run_id=run.run_id,
                    stage=TraceStage.HANDOFF_CREATED,
                    error_code="OUTCOME_UNKNOWN",
                    output_summary=summary,
                    timestamp=now,
                )
                return result(
                    handoff_case=handoff_case,
                    message=f"Outcome unknown; handed to operator. {summary}{not_performed}",
                )

            status = VoiceRunStatus.PARTIALLY_COMPLETED if executed else VoiceRunStatus.FAILED
            self._set_status(run, status, now)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.FAILED,
                tool_name=stopped.tool_name,
                error_code=run.failure_code,
                error_message=stopped.message,
                output_summary=summary,
                timestamp=now,
            )
            prefix = (
                "Partially completed; nothing was rolled back."
                if executed
                else "Nothing was completed."
            )
            return result(message=f"{stopped.message} {prefix} {summary}{not_performed}")

        summary = f"Executed and verified approved plan: {', '.join(executed)}. {self._step_summary(steps)}"
        if plan.unsupported_actions:
            handoff_case = self.handoff_service.create_case(
                run_id=run.run_id,
                reason=f"Requested actions not supported by the system: {unsupported}.",
                original_request=understand_result.transcript.text,
                blocked_actions=[a.value for a in plan.unsupported_actions],
                attempted_actions=executed,
                recommended_action=f"Perform manually: {unsupported}.",
                interpreted_request=interpreted,
                evidence=self._step_evidence(steps),
                now=now,
            )
            self._set_status(run, VoiceRunStatus.HANDOFF, now)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.HANDOFF_CREATED,
                output_summary=f"{summary} Unsupported actions handed off: {unsupported}",
                timestamp=now,
            )
            return result(handoff_case=handoff_case, message=f"{summary}{not_performed}")

        self._set_status(run, VoiceRunStatus.COMPLETED, now)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.COMPLETED,
            output_summary=summary,
            timestamp=now,
        )
        return result(message=summary)

    @staticmethod
    def _step_outcome(tool_name: str, outcome: ExecutionOutcome) -> StepOutcome:
        execution = outcome.execution
        verification = outcome.verification
        if (
            outcome.success
            and verification is not None
            and verification.status is VerificationStatus.VERIFIED
        ):
            status = StepStatus.VERIFIED
        elif execution.status is ToolExecutionStatus.FAILED:
            status = StepStatus.FAILED
        else:
            # Tool outcome UNKNOWN, or acknowledged but not verified by read-back.
            status = StepStatus.UNKNOWN
        entity_id = outcome.tool_result.data.get(_ENTITY_ID_KEY.get(tool_name, ""))
        return StepOutcome(
            tool_name=tool_name,
            status=status,
            execution_status=execution.status.value,
            verification_status=verification.status.value if verification else None,
            entity_id=str(entity_id) if entity_id else None,
            error_code=execution.error_code or outcome.tool_result.error_code,
            message=outcome.message,
            reconciled=outcome.reconciled,
        )

    def _step_summary(self, steps: list[StepOutcome]) -> str:
        """
        Per-step summary whose wording comes from the stored records (P2-F):
        a verified order reads as e.g. "create_order [order 1a2b… DRAFT]", never
        as "confirmed" or "dispatched" unless the record says so.
        """
        groups: dict[StepStatus, list[str]] = {}
        for step in steps:
            label = step.tool_name
            if step.status is StepStatus.VERIFIED:
                record = self._record_label(step)
                if record:
                    label = f"{step.tool_name} [{record}]"
            groups.setdefault(step.status, []).append(label)
        labels = {
            StepStatus.VERIFIED: "Verified",
            StepStatus.FAILED: "Failed",
            StepStatus.UNKNOWN: "Outcome unknown",
            StepStatus.NOT_ATTEMPTED: "Not attempted",
        }
        return " ".join(
            f"{labels[status]}: {', '.join(groups[status])}."
            for status in labels
            if status in groups
        )

    def _record_label(self, step: StepOutcome) -> str | None:
        if not step.entity_id:
            return None
        entity_id = UUID(step.entity_id)
        record: Any = None
        kind = _ENTITY_ID_KEY.get(step.tool_name, "").removesuffix("_id")
        if kind == "order":
            record = self.repositories.orders.get_by_id(order_id=entity_id)
        elif kind == "invoice":
            record = self.repositories.invoices.get_by_id(invoice_id=entity_id)
        elif kind == "dispatch":
            record = self.repositories.dispatches.get_by_id(dispatch_id=entity_id)
        if record is None:
            return None
        return f"{kind} {entity_id} {record.status.value}"

    @staticmethod
    def _step_evidence(steps: list[StepOutcome]) -> list[str]:
        return [
            f"{s.tool_name}: {s.status.value} (execution={s.execution_status}, "
            f"verification={s.verification_status}, record={s.entity_id}, error={s.error_code})"
            for s in steps
        ]

    @staticmethod
    def _handoff_interpretation(
        understand_result: UnderstandResult,
        plan: ExecutionPlan,
        approval: Approval,
        steps: list[StepOutcome],
    ) -> dict[str, Any]:
        """Everything an operator needs to continue without replaying the request."""
        return {
            **interpret_semantic_state(understand_result.semantic_state),
            "run_id": str(plan.run_id),
            "plan_id": str(plan.plan_id),
            "plan_fingerprint": plan.fingerprint,
            "snapshot_version": plan.snapshot_version,
            "approval_id": str(approval.approval_id),
            "planned_tools": plan.tool_names,
            "steps": [step.model_dump(mode="json") for step in steps],
        }

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

    def _understand(
        self,
        *,
        transcript: Transcript,
        run: VoiceRun,
        now: datetime,
        semantic_state: SemanticState | None = None,
        trace_note: str | None = None,
        audio: AudioMetadata | None = None,
    ) -> UnderstandResult:
        run.transcript_id = transcript.transcript_id
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.TRANSCRIBED,
            input_ref=trace_note or f"{transcript.provider}:{transcript.text[:60]}",
            output_summary=transcript.text,
            timestamp=now,
        )
        if semantic_state is None:
            semantic_state = self.compiler.compile(transcript, run_id=run.run_id)
        # Measured audio quality (voice input) gates actionability like the UNDERSTAND
        # pipeline: unusable audio is BLOCKED.
        evaluation = self.evaluator.evaluate(semantic_state, transcript=transcript, audio=audio)
        understand_result = UnderstandResult(
            result_id=uuid4(),
            run_id=run.run_id,
            transcript=transcript,
            semantic_state=semantic_state,
            evaluation=evaluation,
            created_at=now,
        )
        run.semantic_state_id = semantic_state.semantic_state_id
        self.repositories.understand_results.save(understand_result=understand_result)
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
        utterance_time: datetime | None = None,
        confirmed_warning_keys: frozenset[str] = frozenset(),
    ) -> _ActAssessment:
        # Relative dates resolve against when the user spoke; validity against now.
        context = self.context_resolver.resolve(
            semantic_state=semantic_state,
            run_id=run.run_id,
            run_timestamp=now,
            utterance_timestamp=utterance_time,
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
            confirmed_warning_keys=confirmed_warning_keys,
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
        clarification = ClarificationRecord(
            clarification_id=uuid4(),
            run_id=run.run_id,
            status=ClarificationStatus.OPEN,
            reason_code=code.value,
            reason=reason,
            unresolved=self._unresolved_items(understand_result, act),
            understood=interpret_semantic_state(understand_result.semantic_state),
            understand_result=understand_result,
            created_at=now,
        )
        self.repositories.clarifications.save(clarification=clarification)
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.CLARIFICATION_RECORDED,
            output_summary=(
                f"Clarification {clarification.clarification_id}: "
                f"{len(clarification.unresolved)} unresolved item(s)"
            ),
            timestamp=now,
        )
        result = self._result(
            run, understand_result, act=act, decision=decision, plan=plan, message=reason
        )
        result.clarification = clarification
        return result

    @staticmethod
    def _unresolved_items(
        understand_result: UnderstandResult, act: _ActAssessment | None
    ) -> list[dict[str, Any]]:
        """
        What is missing or uncertain, from evidence only (P2-J): Input Evaluation
        reasons that stop execution, semantic ambiguities with every candidate,
        and validation checks that failed or warned. Nothing is guessed.
        """
        items: list[dict[str, Any]] = []
        for reason in understand_result.evaluation.reasons:
            if reason.effect in {Actionability.CLARIFICATION_REQUIRED, Actionability.BLOCKED}:
                items.append(
                    {
                        "source": "INPUT_EVALUATION",
                        "code": reason.code.value,
                        "slot": reason.slot.value if reason.slot else None,
                        "message": reason.message,
                    }
                )
        for ambiguity in understand_result.semantic_state.ambiguities:
            items.append(
                {
                    "source": "SEMANTIC_AMBIGUITY",
                    "code": ambiguity.ambiguity_type.value,
                    "slot": ambiguity.slot.value,
                    "message": ambiguity.description,
                    "candidates": list(ambiguity.candidates),
                }
            )
        if act is not None:
            for check in act.validation.checks:
                if check.status in {ValidationStatus.FAILED, ValidationStatus.WARNING}:
                    items.append(
                        {
                            "source": "VALIDATION",
                            "code": check.check_type,
                            "slot": check.field,
                            "message": check.message,
                            "status": check.status.value,
                        }
                    )
            for error in act.context.business_context.resolution_errors:
                items.append({"source": "CONTEXT_RESOLUTION", "message": error})
        return items

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
        understand_result: UnderstandResult | None,
        *,
        message: str,
        act: _ActAssessment | None = None,
        decision: Decision | None = None,
        approval: Approval | None = None,
        handoff_case: HandoffCase | None = None,
        plan: ExecutionPlan | None = None,
        outcome: ExecutionOutcome | None = None,
        executed: list[str] | None = None,
        steps: list[StepOutcome] | None = None,
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
            step_outcomes=steps or [],
            tax_calculation=act.context.tax_calculation if act else None,
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
        """Preprocess and transcribe an audio artifact, then process the real transcript."""
        t = now or self.clock()
        if not self.preprocess_audio_service or not self.transcribe_audio_service:
            raise RuntimeError("Audio services not configured on orchestrator.")
        run = self.repositories.runs.get_by_id(run_id=run_id) if run_id else None
        if run is None:
            run = self.start_run(run_id=run_id, now=t)
        run.audio_artifact_id = artifact.artifact_id

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
        return self.process_transcript(
            transcript=transcript, run_id=run.run_id, now=t, audio=processed.metadata
        )
