from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.handoff import (
    HandoffCase,
    HandoffPriority,
    HandoffStatus,
)
from vaaniflow.domain.models.validation import ValidationResult, ValidationStatus
from vaaniflow.domain.policies.decision import Decision
from vaaniflow.domain.policies.risk import RiskAssessment, RiskLevel
from vaaniflow.domain.schemas.semantic import SemanticState
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


class HandoffService:
    """
    Service for creating, tracking, and resolving structured human handoff cases.

    Escalates situations requiring human judgment without losing context,
    uncertainties, or evidence.
    """

    def __init__(self, repositories: SyntheticRepositories) -> None:
        self._repositories = repositories

    def create_case(
        self,
        *,
        run_id: UUID,
        reason: str,
        original_request: str,
        priority: HandoffPriority = HandoffPriority.HIGH,
        customer_id: UUID | None = None,
        interpreted_request: dict[str, Any] | None = None,
        uncertainties: list[str] | None = None,
        evidence: list[str] | None = None,
        attempted_actions: list[str] | None = None,
        blocked_actions: list[str] | None = None,
        recommended_action: str | None = None,
        risk_summary: str | None = None,
        now: datetime | None = None,
    ) -> HandoffCase:
        """Create and store an explicit structured handoff packet."""
        current_time = now or datetime.now(UTC)
        case = HandoffCase(
            handoff_id=uuid4(),
            run_id=run_id,
            status=HandoffStatus.CREATED,
            priority=priority,
            reason=reason,
            customer_id=customer_id,
            original_request=original_request,
            interpreted_request=interpreted_request or {},
            uncertainties=uncertainties or [],
            evidence=evidence or [],
            attempted_actions=attempted_actions or [],
            blocked_actions=blocked_actions or [],
            recommended_action=recommended_action,
            risk_summary=risk_summary,
            created_at=current_time,
        )
        self._repositories.handoffs.save(handoff_case=case)
        return case

    def create_case_from_evaluation(
        self,
        *,
        run_id: UUID,
        original_request: str,
        validation_result: ValidationResult,
        risk_assessment: RiskAssessment,
        decision: Decision,
        semantic_state: SemanticState | None = None,
        customer_id: UUID | None = None,
        attempted_actions: list[str] | None = None,
        blocked_actions: list[str] | None = None,
        recommended_action: str | None = None,
        now: datetime | None = None,
    ) -> HandoffCase:
        """Construct a structured handoff case directly from validation, risk, and policy decisions."""
        priority_map = {
            RiskLevel.CRITICAL: HandoffPriority.CRITICAL,
            RiskLevel.HIGH: HandoffPriority.HIGH,
            RiskLevel.MEDIUM: HandoffPriority.NORMAL,
            RiskLevel.LOW: HandoffPriority.LOW,
        }
        priority = priority_map.get(risk_assessment.level, HandoffPriority.HIGH)

        # Collect uncertainties
        uncertainties: list[str] = []
        for check in validation_result.checks:
            if check.status in {ValidationStatus.FAILED, ValidationStatus.WARNING}:
                uncertainties.append(f"[{check.check_type}] {check.message}")
        for factor in risk_assessment.factors:
            uncertainties.append(f"[{factor.factor_type.value}] {factor.description}")

        # Collect evidence
        evidence: list[str] = []
        for check in validation_result.checks:
            evidence.extend(check.evidence)

        # Collect interpreted request summary
        interpreted: dict[str, Any] = {}
        if semantic_state is not None:
            interpreted = {
                "intent": semantic_state.intent.value,
                "actions": [a.action_type.value for a in semantic_state.requested_actions],
                "customer": semantic_state.customer.normalized_text
                if semantic_state.customer
                else None,
                "items_count": len(semantic_state.items),
                "confidence": float(semantic_state.intent_confidence.score),
            }

        # Derive recommended action if not explicitly given
        derived_recommendation = recommended_action
        if not derived_recommendation:
            reasons_lower = decision.reason.lower()
            if "ambiguity" in reasons_lower or "ambiguous" in reasons_lower:
                derived_recommendation = (
                    "Clarify entity identity with the operator or caller before taking action."
                )
            elif "shortage" in reasons_lower or "stock" in reasons_lower:
                derived_recommendation = (
                    "Review inventory across alternative warehouses or confirm partial dispatch."
                )
            elif "quote" in reasons_lower or "expired" in reasons_lower:
                derived_recommendation = (
                    "Provide updated rate quote for owner approval before generating invoice."
                )
            else:
                derived_recommendation = (
                    "Review transaction details and manually approve or modify order."
                )

        # Derive blocked actions if not given
        derived_blocked: list[str] = blocked_actions or []
        if not derived_blocked and semantic_state is not None:
            derived_blocked = [
                f"execute_{a.action_type.value.lower()}" for a in semantic_state.requested_actions
            ]

        derived_attempted: list[str] = attempted_actions or [
            "audio_transcription",
            "semantic_compilation",
            "context_resolution",
            "deterministic_validation",
            "policy_evaluation",
        ]

        return self.create_case(
            run_id=run_id,
            reason=decision.reason,
            original_request=original_request,
            priority=priority,
            customer_id=customer_id,
            interpreted_request=interpreted,
            uncertainties=uncertainties,
            evidence=evidence,
            attempted_actions=derived_attempted,
            blocked_actions=derived_blocked,
            recommended_action=derived_recommendation,
            risk_summary=f"Risk Level: {risk_assessment.level.value} (score={risk_assessment.score}). {decision.reason}",
            now=now,
        )

    def resolve_case(
        self,
        *,
        handoff_id: UUID,
        status: HandoffStatus = HandoffStatus.RESOLVED,
        resolved_by: UUID | None = None,
        now: datetime | None = None,
    ) -> HandoffCase:
        """Resolve a handoff case."""
        case = self._repositories.handoffs.get_by_id(handoff_id=handoff_id)
        if case is None:
            raise ValueError(f"Handoff case {handoff_id} not found.")

        current_time = now or datetime.now(UTC)
        case.status = status
        case.resolved_at = current_time
        if resolved_by is not None:
            case.assigned_to = resolved_by
        self._repositories.handoffs.save(handoff_case=case)
        return case

    def assign_case(
        self,
        *,
        handoff_id: UUID,
        assigned_to: UUID,
    ) -> HandoffCase:
        """Assign an open handoff case to a human operator."""
        case = self._repositories.handoffs.get_by_id(handoff_id=handoff_id)
        if case is None:
            raise ValueError(f"Handoff case {handoff_id} not found.")

        case.assigned_to = assigned_to
        case.status = HandoffStatus.ASSIGNED
        self._repositories.handoffs.save(handoff_case=case)
        return case

    def get_case(self, *, handoff_id: UUID) -> HandoffCase | None:
        """Retrieve a handoff case by ID."""
        return self._repositories.handoffs.get_by_id(handoff_id=handoff_id)

    def list_cases_for_run(self, *, run_id: UUID) -> list[HandoffCase]:
        """List all handoff cases associated with a voice run."""
        return self._repositories.handoffs.list_by_run(run_id=run_id)

    def list_open_cases(self) -> list[HandoffCase]:
        """List all active handoff cases awaiting operator attention."""
        all_cases = self._repositories.handoffs.list_all()
        return [
            c
            for c in all_cases
            if c.status in {HandoffStatus.CREATED, HandoffStatus.OPEN, HandoffStatus.ASSIGNED}
        ]
