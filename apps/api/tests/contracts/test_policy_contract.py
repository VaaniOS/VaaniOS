from uuid import uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.domain.policies.authorization import (
    AuthorizationAction,
    AuthorizationResult,
    AuthorizationStatus,
)
from vaaniflow.domain.policies.decision import (
    Decision,
    DecisionReasonCode,
    DecisionType,
)
from vaaniflow.domain.policies.risk import (
    RiskAssessment,
    RiskFactor,
    RiskFactorType,
    RiskLevel,
)


def test_execute_decision_accepts_valid_contract() -> None:
    decision = Decision(
        decision_id=uuid4(),
        run_id=uuid4(),
        decision=DecisionType.EXECUTE,
        reason_code=DecisionReasonCode.VALIDATED_LOW_RISK,
        reason="Request is validated and low risk.",
        allowed=True,
        policy_version="1.0",
    )

    assert decision.decision == DecisionType.EXECUTE
    assert decision.allowed is True
    assert decision.requires_approval is False


def test_high_risk_action_can_require_approval() -> None:
    decision = Decision(
        decision_id=uuid4(),
        run_id=uuid4(),
        decision=DecisionType.APPROVAL_REQUIRED,
        reason_code=DecisionReasonCode.HIGH_RISK_ACTION,
        reason="Irreversible dispatch requires explicit approval.",
        allowed=False,
        requires_approval=True,
        policy_version="1.0",
    )

    assert decision.decision == DecisionType.APPROVAL_REQUIRED
    assert decision.requires_approval is True
    assert decision.allowed is False


def test_risk_assessment_accepts_multiple_factors() -> None:
    assessment = RiskAssessment(
        risk_assessment_id=uuid4(),
        run_id=uuid4(),
        level=RiskLevel.HIGH,
        score=0.82,
        factors=[
            RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.FINANCIAL_EXPOSURE,
                level=RiskLevel.HIGH,
                score=0.80,
                description="Order has significant financial exposure.",
            ),
            RiskFactor(
                factor_id=uuid4(),
                factor_type=RiskFactorType.IRREVERSIBILITY,
                level=RiskLevel.HIGH,
                score=0.90,
                description="Dispatch creates an external side effect.",
            ),
        ],
        assessor_version="1.0",
    )

    assert assessment.level == RiskLevel.HIGH
    assert assessment.score == 0.82
    assert len(assessment.factors) == 2


def test_risk_score_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            risk_assessment_id=uuid4(),
            run_id=uuid4(),
            level=RiskLevel.CRITICAL,
            score=1.5,
            assessor_version="1.0",
        )


def test_authorization_can_require_approval() -> None:
    authorization = AuthorizationResult(
        authorization_id=uuid4(),
        run_id=uuid4(),
        action=AuthorizationAction.DISPATCH,
        status=AuthorizationStatus.REQUIRES_APPROVAL,
        actor_id=uuid4(),
        reason="Dispatch requires owner approval.",
        policy_version="1.0",
        approval_required=True,
    )

    assert authorization.status == AuthorizationStatus.REQUIRES_APPROVAL
    assert authorization.approval_required is True


def test_denied_authorization_is_explicit() -> None:
    authorization = AuthorizationResult(
        authorization_id=uuid4(),
        run_id=uuid4(),
        action=AuthorizationAction.ISSUE_INVOICE,
        status=AuthorizationStatus.DENIED,
        reason="Actor is not authorized to issue invoices.",
        policy_version="1.0",
    )

    assert authorization.status == AuthorizationStatus.DENIED
    assert authorization.approval_required is False


def test_policy_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Decision(
            decision_id=uuid4(),
            run_id=uuid4(),
            decision=DecisionType.BLOCKED,
            reason_code=DecisionReasonCode.POLICY_VIOLATION,
            reason="Action violates policy.",
            allowed=False,
            policy_version="1.0",
            totally_fake_field=True,
        )
