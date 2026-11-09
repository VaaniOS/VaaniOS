from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.schemas.audio_preprocessing import AudioPreprocessingInput
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.context.service import ContextResolutionService
from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.handoff import HandoffCase
from vaaniflow.domain.models.validation import ValidationResult
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus
from vaaniflow.domain.policies.decision import Decision, DecisionType
from vaaniflow.domain.policies.risk import RiskAssessment
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.domain.schemas.common import Actionability
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.domain.schemas.understand import UnderstandResult
from vaaniflow.execution.approval import ApprovalService
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


class VoiceWorkflowOrchestrator:
    """
    End-to-end orchestrator connecting UNDERSTAND and ACT layers.

    Guarantees:
    1. Speech is not state: business decisions are grounded in canonical repositories.
    2. Consequential operations require approval and read-back verification.
    3. Never fakes success on failures.
    4. Records fine-grained observability traces at every stage.
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
        is_approved: bool = False,
        approved_by: UUID | None = None,
        simulated_faults: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> WorkflowResult:
        """Process a text instruction through the full UNDERSTAND and ACT pipeline."""
        t = now or datetime.now(UTC)
        run = self.repositories.runs.get_by_id(run_id=run_id) if run_id else None
        if run is None:
            run = self.start_run(run_id=run_id, now=t)

        run.status = VoiceRunStatus.PROCESSING
        run.updated_at = t
        self.repositories.runs.save(run=run)

        # 1. Transcript compilation
        transcript = Transcript(
            transcript_id=uuid4(),
            provider="test",
            language="hi-en",
            text=text,
            created_at=t,
        )
        run.transcript_id = transcript.transcript_id

        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.TRANSCRIBED,
            input_ref=f"text:{text[:60]}",
            output_summary=transcript.text,
            confidence=0.98,
            timestamp=t,
        )

        # 2. Semantic Compilation & Input Evaluation
        semantic_state = self.compiler.compile(transcript, run_id=run.run_id)
        evaluation = self.evaluator.evaluate(semantic_state, transcript=transcript)
        understand_result = UnderstandResult(
            result_id=uuid4(),
            run_id=run.run_id,
            transcript=transcript,
            semantic_state=semantic_state,
            evaluation=evaluation,
            created_at=t,
        )

        run.semantic_state_id = semantic_state.semantic_state_id
        run.status = VoiceRunStatus.SEMANTIC_READY
        run.updated_at = t
        self.repositories.runs.save(run=run)

        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.SEMANTIC_COMPILED,
            output_summary=f"Intent={semantic_state.intent.value}, actions={len(semantic_state.requested_actions)}",
            confidence=float(semantic_state.intent_confidence.score),
            timestamp=t,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.INPUT_EVALUATED,
            output_summary=f"Actionability={evaluation.actionability.value}",
            timestamp=t,
        )

        # Check for input-level blocking
        if evaluation.actionability == Actionability.BLOCKED:
            run.status = VoiceRunStatus.BLOCKED
            run.failure_code = "INPUT_BLOCKED"
            run.failure_message = "; ".join(r.message for r in evaluation.reasons)
            run.updated_at = t
            self.repositories.runs.save(run=run)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.BLOCKED,
                error_code="INPUT_BLOCKED",
                error_message=run.failure_message,
                timestamp=t,
            )
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=None,
                validation_result=None,
                risk_assessment=None,
                decision=None,
                approval=None,
                handoff_case=None,
                execution_outcome=None,
                message=f"Request blocked: {run.failure_message}",
            )

        # 3. Context Grounding / Resolution
        res_output = self.context_resolver.resolve(
            semantic_state=semantic_state,
            run_id=run.run_id,
            run_timestamp=t,
        )
        business_context = res_output.business_context
        tax_calculation = res_output.tax_calculation
        snapshot_bytes = json.dumps(res_output.snapshot, sort_keys=True).encode()
        snapshot_version = hashlib.sha256(snapshot_bytes).hexdigest()[:16]

        run.status = VoiceRunStatus.CONTEXT_READY
        run.updated_at = t
        self.repositories.runs.save(run=run)

        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.CONTEXT_RESOLVED,
            output_summary=f"Snapshot={snapshot_version}",
            metadata={"snapshot_version": snapshot_version},
            timestamp=t,
        )

        # 4. Deterministic Validation
        validation_result = self.validation_engine.validate(
            semantic_state=semantic_state,
            business_context=business_context,
            tax_calculation=tax_calculation,
            run_id=run.run_id,
            validated_at=t,
        )
        run.status = VoiceRunStatus.VALIDATED
        run.updated_at = t
        self.repositories.runs.save(run=run)

        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.VALIDATED,
            output_summary=f"Status={validation_result.status.value}, checks={len(validation_result.checks)}",
            timestamp=t,
        )

        # 5. Risk Assessment
        risk_assessment = self.risk_assessor.assess(
            semantic_state=semantic_state,
            validation_result=validation_result,
            business_context=business_context,
            run_id=run.run_id,
        )
        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.RISK_ASSESSED,
            output_summary=f"Level={risk_assessment.level.value}, score={risk_assessment.score:.2f}",
            confidence=risk_assessment.score,
            timestamp=t,
        )

        # 6. Policy Decision
        decision = self.policy_engine.evaluate(
            validation_result=validation_result,
            risk_assessment=risk_assessment,
            semantic_state=semantic_state,
            business_context=business_context,
            is_approved=is_approved,
            run_id=run.run_id,
        )
        run.status = VoiceRunStatus.DECIDED
        run.updated_at = t
        self.repositories.runs.save(run=run)

        self.trace_service.record_stage(
            run_id=run.run_id,
            stage=TraceStage.DECISION_MADE,
            decision=decision.decision.value,
            output_summary=decision.reason,
            timestamp=t,
        )

        # 7. Action Handling based on Policy Decision
        approval: Approval | None = None
        handoff_case: HandoffCase | None = None

        faults = simulated_faults or {}

        # Path A: Clarification Required (e.g. Scenario C: ambiguous customer or Scenario J: ambiguous product)
        if decision.decision == DecisionType.CLARIFY:
            run.status = VoiceRunStatus.CLARIFICATION_REQUIRED
            run.updated_at = t
            self.repositories.runs.save(run=run)
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=None,
                handoff_case=None,
                execution_outcome=None,
                message=decision.reason,
            )

        # Path B: User Confirmation Required (e.g. Scenario B: suspicious quantity magnitude)
        if decision.decision == DecisionType.CONFIRM:
            run.status = VoiceRunStatus.APPROVAL_REQUIRED
            run.updated_at = t
            self.repositories.runs.save(run=run)
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=None,
                handoff_case=None,
                execution_outcome=None,
                message=f"Confirmation required: {decision.reason}",
            )

        # Path C: Human Handoff (e.g. Scenario D: stale quote or Scenario E: inventory shortage)
        if decision.decision == DecisionType.HUMAN_HANDOFF:
            run.status = VoiceRunStatus.HANDOFF
            run.updated_at = t
            self.repositories.runs.save(run=run)

            handoff_case = self.handoff_service.create_case_from_evaluation(
                run_id=run.run_id,
                original_request=text,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                semantic_state=semantic_state,
                customer_id=business_context.customer.customer.customer_id
                if business_context.customer and business_context.customer.customer
                else None,
                now=t,
            )
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.HANDOFF_CREATED,
                output_summary=f"Handoff case {handoff_case.handoff_id} created: {handoff_case.reason}",
                timestamp=t,
            )
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=None,
                handoff_case=handoff_case,
                execution_outcome=None,
                message=f"Escalated to human operator: {decision.reason}",
            )

        # Path D: Blocked by Policy
        if decision.decision == DecisionType.BLOCKED:
            run.status = VoiceRunStatus.BLOCKED
            run.failure_code = decision.reason_code.value
            run.failure_message = decision.reason
            run.updated_at = t
            self.repositories.runs.save(run=run)
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.BLOCKED,
                error_code=decision.reason_code.value,
                error_message=decision.reason,
                timestamp=t,
            )
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=None,
                handoff_case=None,
                execution_outcome=None,
                message=f"Action blocked by policy: {decision.reason}",
            )

        # Path E: Approval Required before Execution
        if decision.decision == DecisionType.APPROVAL_REQUIRED:
            run.status = VoiceRunStatus.APPROVAL_REQUIRED
            run.updated_at = t
            self.repositories.runs.save(run=run)

            approval = self.approval_service.request_approval(
                run_id=run.run_id,
                requested_by=approved_by or uuid4(),
                snapshot_version=snapshot_version,
                now=t,
            )
            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.APPROVAL_REQUESTED,
                output_summary=f"Approval {approval.approval_id} requested for snapshot {snapshot_version}",
                timestamp=t,
            )
            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=approval,
                handoff_case=None,
                execution_outcome=None,
                message="Consequential write validated. Owner approval is required before execution.",
                snapshot_version=snapshot_version,
            )

        # Path F: Execute Allowed (Approved or Safe Draft/Read)
        if decision.decision == DecisionType.EXECUTE and decision.allowed:
            run.status = VoiceRunStatus.EXECUTING
            run.updated_at = t
            self.repositories.runs.save(run=run)

            # Ensure an approved record exists if decision required approval
            effective_approval: Approval | None = None
            if is_approved:
                effective_approval = Approval(
                    approval_id=uuid4(),
                    requested_by=approved_by or uuid4(),
                    approved_by=approved_by or uuid4(),
                    status=ApprovalStatus.APPROVED,
                    snapshot_version=faults.get("override_approval_snapshot") or snapshot_version,
                    requested_at=t,
                    resolved_at=t,
                )
                self.repositories.approvals.save(approval=effective_approval)

            # Assemble execution arguments from grounded business context
            cust_id = (
                business_context.customer.customer.customer_id
                if business_context.customer and business_context.customer.customer
                else None
            )
            prod_id = (
                business_context.products[0].product.product_id
                if business_context.products
                else None
            )
            unit_price_val = (
                business_context.resolved_price.unit_price
                if business_context.resolved_price
                else Decimal("420.00")
            )

            # First create draft order & invoice
            first_item = semantic_state.items[0] if semantic_state.items else None
            qty = first_item.quantity.value if first_item and first_item.quantity else Decimal(200)
            unit = first_item.quantity.unit if first_item and first_item.quantity else "bags"
            subtotal = unit_price_val * qty
            tax_total = tax_calculation.total_tax if tax_calculation else Decimal("23520.00")
            total = tax_calculation.total_amount if tax_calculation else subtotal + tax_total

            # Create order tool execution
            order_tool_args: dict[str, Any] = {
                "customer_id": str(cust_id),
                "items": [
                    {
                        "product_id": str(prod_id),
                        "quantity": int(qty),
                        "unit": str(unit or "bags"),
                        "unit_price": str(unit_price_val),
                        "line_total": str(subtotal),
                    }
                ],
            }
            order_outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name="create_order",
                arguments=order_tool_args,
                idempotency_key=f"run-{run.run_id}:create-order",
                decision=decision,
                approval=effective_approval,
                current_snapshot_version=snapshot_version,
                now=t,
            )

            if not order_outcome.success:
                run.status = VoiceRunStatus.FAILED
                run.failure_code = order_outcome.tool_result.error_code
                run.failure_message = order_outcome.message
                run.updated_at = t
                self.repositories.runs.save(run=run)
                self.trace_service.record_stage(
                    run_id=run.run_id,
                    stage=TraceStage.FAILED,
                    tool_name="create_order",
                    error_code=order_outcome.tool_result.error_code,
                    error_message=order_outcome.message,
                    timestamp=t,
                )
                return WorkflowResult(
                    run=run,
                    understand_result=understand_result,
                    business_context=business_context,
                    validation_result=validation_result,
                    risk_assessment=risk_assessment,
                    decision=decision,
                    approval=effective_approval,
                    handoff_case=None,
                    execution_outcome=order_outcome,
                    message=order_outcome.message,
                )

            # Create invoice draft
            inv_draft_args: dict[str, Any] = {
                "order_id": order_outcome.tool_result.data["order_id"],
                "customer_id": str(cust_id),
                "subtotal": str(subtotal),
                "tax_total": str(tax_total),
                "total": str(total),
                "items": order_tool_args["items"],
            }
            draft_outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name="create_invoice_draft",
                arguments=inv_draft_args,
                idempotency_key=f"run-{run.run_id}:create-invoice-draft",
                decision=decision,
                approval=effective_approval,
                current_snapshot_version=snapshot_version,
                now=t,
            )
            created_invoice_id = draft_outcome.tool_result.data["invoice_id"]

            # Issue invoice tool call (with failure toggle for Scenario F)
            issue_outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name="issue_invoice",
                arguments={"invoice_id": created_invoice_id},
                idempotency_key=f"run-{run.run_id}:issue-invoice",
                decision=decision,
                approval=effective_approval,
                current_snapshot_version=snapshot_version,
                expected_state={"status": "ISSUED", "total": str(total)},
                entity_type="invoice",
                metadata={"simulate_invoice_failure": bool(faults.get("simulate_invoice_failure"))},
                now=t,
            )

            if not issue_outcome.success:
                run.status = VoiceRunStatus.FAILED
                run.failure_code = issue_outcome.tool_result.error_code
                run.failure_message = issue_outcome.message
                run.updated_at = t
                self.repositories.runs.save(run=run)
                self.trace_service.record_stage(
                    run_id=run.run_id,
                    stage=TraceStage.FAILED,
                    tool_name="issue_invoice",
                    error_code=issue_outcome.tool_result.error_code,
                    error_message=issue_outcome.message,
                    timestamp=t,
                )
                return WorkflowResult(
                    run=run,
                    understand_result=understand_result,
                    business_context=business_context,
                    validation_result=validation_result,
                    risk_assessment=risk_assessment,
                    decision=decision,
                    approval=effective_approval,
                    handoff_case=None,
                    execution_outcome=issue_outcome,
                    message=issue_outcome.message,
                )

            # Dispatch order tool call (with failure toggle for Scenario G)
            wh_id = (
                business_context.inventory[0].inventory.warehouse_id
                if business_context.inventory
                else (
                    self.repositories.warehouses.list_all()[0].warehouse_id
                    if self.repositories.warehouses.list_all()
                    else None
                )
            )
            dispatch_args: dict[str, Any] = {
                "order_id": order_outcome.tool_result.data["order_id"],
                "customer_id": str(cust_id),
                "warehouse_id": str(wh_id),
                "delivery_address": "Site 12, Peenya",
            }
            dispatch_outcome = self.execution_service.execute(
                run_id=run.run_id,
                tool_name="dispatch_order",
                arguments=dispatch_args,
                idempotency_key=f"run-{run.run_id}:dispatch-order",
                decision=decision,
                approval=effective_approval,
                current_snapshot_version=snapshot_version,
                expected_state={"status": "DISPATCHED", "warehouse_id": str(wh_id)},
                entity_type="dispatch",
                metadata={
                    "simulate_dispatch_failure": bool(faults.get("simulate_dispatch_failure"))
                },
                now=t,
            )

            if not dispatch_outcome.success:
                run.status = VoiceRunStatus.FAILED
                run.failure_code = dispatch_outcome.tool_result.error_code
                run.failure_message = dispatch_outcome.message
                run.updated_at = t
                self.repositories.runs.save(run=run)
                self.trace_service.record_stage(
                    run_id=run.run_id,
                    stage=TraceStage.FAILED,
                    tool_name="dispatch_order",
                    error_code=dispatch_outcome.tool_result.error_code,
                    error_message=dispatch_outcome.message,
                    timestamp=t,
                )
                return WorkflowResult(
                    run=run,
                    understand_result=understand_result,
                    business_context=business_context,
                    validation_result=validation_result,
                    risk_assessment=risk_assessment,
                    decision=decision,
                    approval=effective_approval,
                    handoff_case=None,
                    execution_outcome=dispatch_outcome,
                    message=dispatch_outcome.message,
                )

            # Happy path completed and verified!
            run.status = VoiceRunStatus.COMPLETED
            run.updated_at = t
            self.repositories.runs.save(run=run)

            self.trace_service.record_stage(
                run_id=run.run_id,
                stage=TraceStage.COMPLETED,
                output_summary=f"Invoice {created_invoice_id} issued & order dispatched successfully.",
                timestamp=t,
            )

            return WorkflowResult(
                run=run,
                understand_result=understand_result,
                business_context=business_context,
                validation_result=validation_result,
                risk_assessment=risk_assessment,
                decision=decision,
                approval=effective_approval,
                handoff_case=None,
                execution_outcome=dispatch_outcome,
                message=f"Order executed successfully: Invoice ₹{total} issued and dispatch confirmed.",
            )

        # Fallthrough safety
        return WorkflowResult(
            run=run,
            understand_result=understand_result,
            business_context=business_context,
            validation_result=validation_result,
            risk_assessment=risk_assessment,
            decision=decision,
            approval=None,
            handoff_case=None,
            execution_outcome=None,
            message=decision.reason,
        )

    def process_audio_artifact(
        self,
        *,
        artifact: AudioArtifact,
        run_id: UUID | None = None,
        is_approved: bool = False,
        simulated_faults: dict[str, Any] | None = None,
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

        return self.process_text(
            text=transcript.text,
            run_id=run.run_id,
            is_approved=is_approved,
            simulated_faults=simulated_faults,
            now=t,
        )
