from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.context.service import ContextResolutionService
from vaaniflow.domain.policies.decision import (
    DecisionReasonCode,
    DecisionType,
)
from vaaniflow.domain.policies.risk import RiskLevel
from vaaniflow.domain.schemas.semantic import SemanticState
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.infrastructure.repositories import SyntheticRepositories
from vaaniflow.policy.engine import PolicyEngine
from vaaniflow.policy.risk import RiskAssessor
from vaaniflow.semantic.compiler import SemanticCompiler
from vaaniflow.validation.engine import ValidationEngine

FIXED_TIME = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

CANONICAL_VOICE_NOTE = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)


def _compile(text: str) -> SemanticState:
    transcript = Transcript(
        transcript_id=uuid4(),
        provider="test",
        language="en-IN",
        text=text,
        created_at=FIXED_TIME,
    )
    return SemanticCompiler(clock=lambda: FIXED_TIME).compile(transcript)


def test_canonical_scenario_requires_owner_approval_prior_to_execution() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()
    risk_assessor = RiskAssessor()
    policy_engine = PolicyEngine()

    semantic_state = _compile(CANONICAL_VOICE_NOTE)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )
    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )
    risk = risk_assessor.assess(
        semantic_state=semantic_state,
        business_context=output.business_context,
        validation_result=validation,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    # 1. Prior to owner approval
    decision_pending = policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=semantic_state,
        business_context=output.business_context,
        is_approved=False,
        run_id=run_id,
    )
    assert decision_pending.decision == DecisionType.APPROVAL_REQUIRED
    assert decision_pending.reason_code == DecisionReasonCode.APPROVAL_REQUIRED
    assert decision_pending.allowed is False
    assert decision_pending.requires_approval is True

    # 2. Once owner explicitly approves
    decision_approved = policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=semantic_state,
        business_context=output.business_context,
        is_approved=True,
        run_id=run_id,
    )
    assert decision_approved.decision == DecisionType.EXECUTE
    assert decision_approved.reason_code == DecisionReasonCode.VALIDATED_LOW_RISK
    assert decision_approved.allowed is True


def test_ambiguous_customer_requires_clarification() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()
    risk_assessor = RiskAssessor()
    policy_engine = PolicyEngine()

    # Note with ambiguous "Sharma"
    note_ambiguous = "Sharma ko 200 bag Ultratech cement dispatch karo."
    semantic_state = _compile(note_ambiguous)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )
    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )
    risk = risk_assessor.assess(
        semantic_state=semantic_state,
        business_context=output.business_context,
        validation_result=validation,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    decision = policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=semantic_state,
        business_context=output.business_context,
        is_approved=False,
        run_id=run_id,
    )
    assert decision.decision == DecisionType.CLARIFY
    assert decision.reason_code == DecisionReasonCode.AMBIGUOUS_INPUT
    assert decision.allowed is False


def test_inventory_shortage_triggers_human_handoff() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()
    risk_assessor = RiskAssessor()
    policy_engine = PolicyEngine()

    note_acc = "Sharma Builders ko 200 bag ACC cement dispatch karo."
    semantic_state = _compile(note_acc)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )
    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )
    risk = risk_assessor.assess(
        semantic_state=semantic_state,
        business_context=output.business_context,
        validation_result=validation,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    decision = policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=semantic_state,
        business_context=output.business_context,
        is_approved=False,
        run_id=run_id,
    )
    assert decision.decision == DecisionType.HUMAN_HANDOFF
    assert decision.reason_code == DecisionReasonCode.CONFLICTING_BUSINESS_DATA
    assert decision.requires_human_handoff is True
    assert decision.allowed is False


def test_suspicious_magnitude_requires_confirmation() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()
    risk_assessor = RiskAssessor()
    policy_engine = PolicyEngine()

    note_2000 = (
        "Arre Suresh, Sharma Builders ko turant 2000 bag Ultratech cement dispatch karo. "
        "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
        "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
    )
    semantic_state = _compile(note_2000)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )
    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )
    risk = risk_assessor.assess(
        semantic_state=semantic_state,
        business_context=output.business_context,
        validation_result=validation,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    decision = policy_engine.evaluate(
        validation_result=validation,
        risk_assessment=risk,
        semantic_state=semantic_state,
        business_context=output.business_context,
        is_approved=False,
        run_id=run_id,
    )
    assert decision.decision == DecisionType.CONFIRM
    assert decision.reason_code == DecisionReasonCode.HIGH_RISK_ACTION
    assert decision.requires_user_confirmation is True
    assert decision.allowed is False


def test_risk_assessment_scoring() -> None:
    repos = SyntheticRepositories()
    context_service = ContextResolutionService(
        customer_repo=repos.customers,
        product_repo=repos.products,
        quote_repo=repos.quotes,
        inventory_repo=repos.inventory,
        tax_rule_repo=repos.tax_rules,
    )
    validator = ValidationEngine()
    risk_assessor = RiskAssessor()

    semantic_state = _compile(CANONICAL_VOICE_NOTE)
    run_id = uuid4()

    output = context_service.resolve(
        semantic_state=semantic_state,
        run_id=run_id,
        run_timestamp=FIXED_TIME,
    )
    validation = validator.validate(
        semantic_state=semantic_state,
        business_context=output.business_context,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )
    risk = risk_assessor.assess(
        semantic_state=semantic_state,
        business_context=output.business_context,
        validation_result=validation,
        tax_calculation=output.tax_calculation,
        run_id=run_id,
    )

    # In canonical note:
    # financial exposure is > 50k, irreversibility is high (dispatch)
    assert risk.level == RiskLevel.HIGH
    assert 0.35 <= risk.score <= 0.70
    factor_types = {f.factor_type for f in risk.factors}
    assert "FINANCIAL_EXPOSURE" in factor_types
    assert "IRREVERSIBILITY" in factor_types
    assert "ENTITY_AMBIGUITY" in factor_types
