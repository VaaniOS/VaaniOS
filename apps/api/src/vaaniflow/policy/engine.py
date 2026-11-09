from uuid import UUID, uuid4

from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.domain.models.validation import ValidationResult, ValidationStatus
from vaaniflow.domain.policies.decision import (
    Decision,
    DecisionReasonCode,
    DecisionType,
)
from vaaniflow.domain.policies.risk import RiskAssessment, RiskLevel
from vaaniflow.domain.schemas.semantic import (
    RequestedActionType,
    SemanticState,
)


class PolicyEngine:
    """
    Deterministic policy and decision engine.

    The decision layer is the authoritative boundary between agent proposals
    and consequential execution. Evaluates validation, risk, and user approvals
    to produce an explicit Decision.
    """

    VERSION = "1.0"

    def evaluate(
        self,
        *,
        validation_result: ValidationResult,
        risk_assessment: RiskAssessment,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        is_approved: bool = False,
        run_id: UUID,
    ) -> Decision:
        # 1. Rule: Identity Ambiguity or Missing Information -> CLARIFY
        identity_failures = [
            c
            for c in validation_result.checks
            if c.check_type in {"CUSTOMER_IDENTITY", "PRODUCT_IDENTITY"}
            and c.status == ValidationStatus.FAILED
        ]
        if identity_failures:
            first = identity_failures[0]
            return Decision(
                decision_id=uuid4(),
                run_id=run_id,
                decision=DecisionType.CLARIFY,
                reason_code=DecisionReasonCode.AMBIGUOUS_INPUT,
                reason=f"Identity ambiguity or missing entity: {first.message}",
                allowed=False,
                requires_user_confirmation=False,
                requires_approval=False,
                requires_human_handoff=False,
                policy_version=self.VERSION,
            )

        # 2. Rule: Suspicious Magnitude or Major Warning -> CONFIRM
        magnitude_warnings = [
            c
            for c in validation_result.checks
            if c.check_type in {"QUANTITY_MAGNITUDE", "PRICE_CONSISTENCY"}
            and c.status == ValidationStatus.WARNING
        ]
        if magnitude_warnings:
            first = magnitude_warnings[0]
            return Decision(
                decision_id=uuid4(),
                run_id=run_id,
                decision=DecisionType.CONFIRM,
                reason_code=DecisionReasonCode.HIGH_RISK_ACTION,
                reason=f"Suspicious order parameters: {first.message}",
                allowed=False,
                requires_user_confirmation=True,
                requires_approval=False,
                requires_human_handoff=False,
                policy_version=self.VERSION,
            )

        # 3. Rule: Conflicting Business Data / Quote Expiry / Shortage -> HUMAN_HANDOFF
        shortage_or_quote_failures = [
            c
            for c in validation_result.checks
            if c.check_type in {"QUOTE_VALIDITY", "INVENTORY_AVAILABILITY"}
            and c.status == ValidationStatus.FAILED
        ]
        if shortage_or_quote_failures:
            first = shortage_or_quote_failures[0]
            return Decision(
                decision_id=uuid4(),
                run_id=run_id,
                decision=DecisionType.HUMAN_HANDOFF,
                reason_code=DecisionReasonCode.CONFLICTING_BUSINESS_DATA,
                reason=f"Business conflict detected: {first.message} Human operator handoff required.",
                allowed=False,
                requires_user_confirmation=False,
                requires_approval=False,
                requires_human_handoff=True,
                policy_version=self.VERSION,
            )

        # 4. Rule: Other Hard Validation Failure -> BLOCKED
        critical_failures = [
            c for c in validation_result.checks if c.status == ValidationStatus.FAILED
        ]
        if critical_failures:
            first = critical_failures[0]
            return Decision(
                decision_id=uuid4(),
                run_id=run_id,
                decision=DecisionType.BLOCKED,
                reason_code=DecisionReasonCode.POLICY_VIOLATION,
                reason=f"Action blocked by policy: {first.message}",
                allowed=False,
                requires_user_confirmation=False,
                requires_approval=False,
                requires_human_handoff=False,
                policy_version=self.VERSION,
            )

        # 5. Rule: Consequential Action (Dispatch, Invoice Creation) Requires Explicit Owner Approval
        action_types = {a.action_type for a in semantic_state.requested_actions}
        is_consequential = (
            RequestedActionType.DISPATCH in action_types
            or RequestedActionType.CREATE_INVOICE_DRAFT in action_types
            or RequestedActionType.REQUEST_APPROVAL in action_types
            or risk_assessment.level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        )

        if is_consequential:
            if not is_approved:
                return Decision(
                    decision_id=uuid4(),
                    run_id=run_id,
                    decision=DecisionType.APPROVAL_REQUIRED,
                    reason_code=DecisionReasonCode.APPROVAL_REQUIRED,
                    reason="Validated consequential action requires explicit owner approval before dispatch or external effect.",
                    allowed=False,
                    requires_user_confirmation=False,
                    requires_approval=True,
                    requires_human_handoff=False,
                    policy_version=self.VERSION,
                )

            # Owner has approved
            return Decision(
                decision_id=uuid4(),
                run_id=run_id,
                decision=DecisionType.EXECUTE,
                reason_code=DecisionReasonCode.VALIDATED_LOW_RISK,
                reason="Owner approval confirmed and state fully validated. Execution permitted.",
                allowed=True,
                requires_user_confirmation=False,
                requires_approval=False,
                requires_human_handoff=False,
                policy_version=self.VERSION,
            )

        # 6. Rule: Safe, Reversible / Read-Only / Draft Action -> EXECUTE
        return Decision(
            decision_id=uuid4(),
            run_id=run_id,
            decision=DecisionType.EXECUTE,
            reason_code=DecisionReasonCode.VALIDATED_LOW_RISK,
            reason="Low-risk, fully validated request permitted to execute.",
            allowed=True,
            requires_user_confirmation=False,
            requires_approval=False,
            requires_human_handoff=False,
            policy_version=self.VERSION,
        )
