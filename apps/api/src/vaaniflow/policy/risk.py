from decimal import Decimal
from uuid import UUID, uuid4

from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.domain.models.tax import TaxCalculation
from vaaniflow.domain.models.validation import ValidationResult, ValidationStatus
from vaaniflow.domain.policies.risk import (
    RiskAssessment,
    RiskFactor,
    RiskFactorType,
    RiskLevel,
)
from vaaniflow.domain.schemas.semantic import (
    RequestedActionType,
    SemanticState,
)


class RiskAssessor:
    """
    Transparent, weighted risk assessment service.

    Answers: 'How dangerous is acting on this proposed state?'
    Produces an interpretable score (0.0 to 1.0) and discrete RiskLevel.
    """

    VERSION = "1.0"

    # Transparent factor weights (sum to 1.0)
    WEIGHT_AMBIGUITY = 0.25
    WEIGHT_IRREVERSIBILITY = 0.25
    WEIGHT_FINANCIAL = 0.20
    WEIGHT_POLICY = 0.15
    WEIGHT_SEMANTIC = 0.15

    def assess(
        self,
        *,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        validation_result: ValidationResult,
        tax_calculation: TaxCalculation | None = None,
        run_id: UUID,
    ) -> RiskAssessment:
        factors: list[RiskFactor] = []

        # 1. Entity Ambiguity Factor
        f_ambiguity = self._assess_entity_ambiguity(business_context)
        factors.append(f_ambiguity)

        # 2. Irreversibility Factor
        f_irreversibility = self._assess_irreversibility(semantic_state)
        factors.append(f_irreversibility)

        # 3. Financial Exposure Factor
        f_financial = self._assess_financial_exposure(
            business_context, semantic_state, tax_calculation
        )
        factors.append(f_financial)

        # 4. Policy & Validation Violation Factor
        f_policy = self._assess_policy_violation(validation_result)
        factors.append(f_policy)

        # 5. Semantic Uncertainty Factor
        f_semantic = self._assess_semantic_uncertainty(semantic_state)
        factors.append(f_semantic)

        # Calculate weighted aggregate score
        raw_score = (
            f_ambiguity.score * self.WEIGHT_AMBIGUITY
            + f_irreversibility.score * self.WEIGHT_IRREVERSIBILITY
            + f_financial.score * self.WEIGHT_FINANCIAL
            + f_policy.score * self.WEIGHT_POLICY
            + f_semantic.score * self.WEIGHT_SEMANTIC
        )
        score = round(min(max(raw_score, 0.0), 1.0), 3)

        if score >= 0.70:
            level = RiskLevel.CRITICAL
        elif score >= 0.35:
            level = RiskLevel.HIGH
        elif score >= 0.15:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        return RiskAssessment(
            risk_assessment_id=uuid4(),
            run_id=run_id,
            level=level,
            score=score,
            factors=factors,
            assessor_version=self.VERSION,
        )

    def _assess_entity_ambiguity(self, business_context: BusinessContext) -> RiskFactor:
        has_ambiguity = bool(
            business_context.resolution_errors or business_context.unresolved_references
        )
        if has_ambiguity:
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.ENTITY_AMBIGUITY,
                level=RiskLevel.HIGH,
                score=1.0,
                description="Entity identity (customer, product, or quote) is unresolved or ambiguous.",
            )

        return RiskFactor(
            factor_id=uuid4(),
            factor_type=RiskFactorType.ENTITY_AMBIGUITY,
            level=RiskLevel.LOW,
            score=0.0,
            description="All entity references uniquely resolved against business records.",
        )

    def _assess_irreversibility(self, semantic_state: SemanticState) -> RiskFactor:
        action_types = {a.action_type for a in semantic_state.requested_actions}

        if RequestedActionType.DISPATCH in action_types:
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.IRREVERSIBILITY,
                level=RiskLevel.HIGH,
                score=0.90,
                description="Physical dispatch creates irreversible real-world side effects.",
            )

        if (
            RequestedActionType.CREATE_INVOICE_DRAFT in action_types
            or RequestedActionType.SEND_NOTIFICATION in action_types
        ):
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.IRREVERSIBILITY,
                level=RiskLevel.MEDIUM,
                score=0.50,
                description="External communication or ledger creation has financial consequence.",
            )

        return RiskFactor(
            factor_id=uuid4(),
            factor_type=RiskFactorType.IRREVERSIBILITY,
            level=RiskLevel.LOW,
            score=0.10,
            description="Read-only operations or internal draft generation are safe and reversible.",
        )

    def _assess_financial_exposure(
        self,
        business_context: BusinessContext,
        semantic_state: SemanticState,
        tax_calculation: TaxCalculation | None,
    ) -> RiskFactor:
        total_val = Decimal(0)

        if tax_calculation is not None:
            total_val = tax_calculation.total_amount
        elif business_context.resolved_price is not None and semantic_state.items:
            unit_p = business_context.resolved_price.unit_price
            qty = semantic_state.items[0].quantity
            if qty is not None:
                total_val = unit_p * qty.value

        if total_val >= Decimal(200_000):
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.FINANCIAL_EXPOSURE,
                level=RiskLevel.CRITICAL,
                score=0.95,
                description=f"Transaction value ({total_val}) exceeds ₹200,000.",
            )

        if total_val >= Decimal(50_000):
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.FINANCIAL_EXPOSURE,
                level=RiskLevel.HIGH,
                score=0.65,
                description=f"Transaction value ({total_val}) is substantial (>= ₹50,000).",
            )

        if total_val >= Decimal(10_000):
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.FINANCIAL_EXPOSURE,
                level=RiskLevel.MEDIUM,
                score=0.35,
                description=f"Transaction value ({total_val}) is moderate.",
            )

        return RiskFactor(
            factor_id=uuid4(),
            factor_type=RiskFactorType.FINANCIAL_EXPOSURE,
            level=RiskLevel.LOW,
            score=0.05,
            description="Transaction value is minimal (< ₹10,000).",
        )

    def _assess_policy_violation(self, validation_result: ValidationResult) -> RiskFactor:
        if validation_result.status == ValidationStatus.FAILED:
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.POLICY_VIOLATION,
                level=RiskLevel.CRITICAL,
                score=1.0,
                description="Deterministic validation failed on one or more business checks.",
            )

        if validation_result.status == ValidationStatus.WARNING:
            return RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.POLICY_VIOLATION,
                level=RiskLevel.HIGH,
                score=0.60,
                description="Deterministic validation reported warnings (e.g. unusual magnitude).",
            )

        return RiskFactor(
            factor_id=uuid4(),
            factor_type=RiskFactorType.POLICY_VIOLATION,
            level=RiskLevel.LOW,
            score=0.0,
            description="All deterministic validation checks passed.",
        )

    def _assess_semantic_uncertainty(self, semantic_state: SemanticState) -> RiskFactor:
        intent_conf = semantic_state.intent_confidence.score
        uncertainty = 1.0 - intent_conf

        if uncertainty > 0.4:
            level = RiskLevel.HIGH
        elif uncertainty > 0.2:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        return RiskFactor(
            factor_id=uuid4(),
            factor_type=RiskFactorType.SEMANTIC_UNCERTAINTY,
            level=level,
            score=round(uncertainty, 3),
            description=f"Intent confidence is {round(intent_conf * 100, 1)}%.",
        )
