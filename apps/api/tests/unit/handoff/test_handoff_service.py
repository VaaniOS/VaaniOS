from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.domain.models.handoff import (
    HandoffPriority,
    HandoffStatus,
)
from vaaniflow.domain.models.validation import (
    ValidationCheck,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)
from vaaniflow.domain.policies.decision import (
    Decision,
    DecisionReasonCode,
    DecisionType,
)
from vaaniflow.domain.policies.risk import RiskAssessment, RiskLevel
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    ActionParty,
    CompilerProvenance,
    IntentType,
    RequestedAction,
    RequestedActionType,
    SemanticEntity,
    SemanticEntityType,
    SemanticState,
    TextSpan,
)
from vaaniflow.handoff.service import HandoffService
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories

_NOW = datetime.now(UTC)


def test_create_case_directly() -> None:
    repos = SyntheticRepositories()
    service = HandoffService(repos)
    run_id = uuid4()

    case = service.create_case(
        run_id=run_id,
        reason="Manual operator intervention requested",
        original_request="Please dispatch 500 bags to site",
        priority=HandoffPriority.HIGH,
        uncertainties=["Delivery location unclear"],
        evidence=["customer:123"],
        attempted_actions=["resolve_customer"],
        blocked_actions=["dispatch_order"],
        recommended_action="Contact customer site supervisor",
        now=_NOW,
    )

    assert case.status == HandoffStatus.CREATED
    assert case.priority == HandoffPriority.HIGH
    assert len(case.uncertainties) == 1

    fetched = service.get_case(handoff_id=case.handoff_id)
    assert fetched is not None
    assert fetched.reason == case.reason


def test_create_case_from_ambiguous_customer_evaluation() -> None:
    repos = SyntheticRepositories()
    service = HandoffService(repos)
    run_id = uuid4()

    val_res = ValidationResult(
        validation_id=uuid4(),
        run_id=run_id,
        status=ValidationStatus.FAILED,
        checks=[
            ValidationCheck(
                check_id=uuid4(),
                check_type="CUSTOMER_IDENTITY",
                status=ValidationStatus.FAILED,
                severity=ValidationSeverity.CRITICAL,
                message="Multiple customers match 'Sharma Builders' (CUST-0042, CUST-0089).",
                evidence=["customer_search:sharma"],
            )
        ],
        validated_at=_NOW,
        validator_version="1.0",
    )

    risk_ass = RiskAssessment(
        risk_assessment_id=uuid4(),
        run_id=run_id,
        level=RiskLevel.HIGH,
        score=0.85,
        factors=[],
        assessor_version="1.0",
    )

    decision = Decision(
        decision_id=uuid4(),
        run_id=run_id,
        decision=DecisionType.HUMAN_HANDOFF,
        reason_code=DecisionReasonCode.AMBIGUOUS_INPUT,
        reason="Customer identity ambiguity detected. Human operator handoff required.",
        allowed=False,
        requires_human_handoff=True,
        policy_version="1.0",
    )

    state = SemanticState(
        semantic_state_id=uuid4(),
        source_transcript_id=uuid4(),
        compiler=CompilerProvenance(compiler_name="test_compiler", compiler_version="1.0"),
        intent=IntentType.CREATE_DISPATCH_ORDER,
        intent_confidence=Confidence(score=0.85, source=ConfidenceSource.RULE),
        customer=SemanticEntity(
            entity_id=uuid4(),
            entity_type=SemanticEntityType.CUSTOMER,
            surface_text="Sharma",
            normalized_text="sharma",
            span=TextSpan(start=17, end=23),
            confidence=Confidence(score=0.8, source=ConfidenceSource.RULE),
        ),
        requested_actions=[
            RequestedAction(
                action_id=uuid4(),
                action_type=RequestedActionType.DISPATCH,
                explicit=True,
                recipient=ActionParty.CUSTOMER,
                surface_text="Send",
                confidence=Confidence(score=0.9, source=ConfidenceSource.RULE),
                span=TextSpan(start=0, end=4),
            )
        ],
        created_at=_NOW,
    )

    case = service.create_case_from_evaluation(
        run_id=run_id,
        original_request="Send 200 bags to Sharma",
        validation_result=val_res,
        risk_assessment=risk_ass,
        decision=decision,
        semantic_state=state,
        now=_NOW,
    )

    assert case.priority == HandoffPriority.HIGH
    assert (
        "ambiguous" in case.recommended_action.lower()
        or "clarify" in case.recommended_action.lower()
    )
    assert "customer_search:sharma" in case.evidence
    assert any("CUSTOMER_IDENTITY" in u for u in case.uncertainties)
    assert "execute_dispatch" in case.blocked_actions
    assert case.interpreted_request["customer"] == "sharma"


def test_handoff_lifecycle_assignment_and_resolution() -> None:
    repos = SyntheticRepositories()
    service = HandoffService(repos)
    run_id = uuid4()
    operator_id = uuid4()

    case = service.create_case(
        run_id=run_id,
        reason="Shortage",
        original_request="Dispatch 500 bags",
        now=_NOW,
    )

    open_cases = service.list_open_cases()
    assert len(open_cases) == 1

    # Assign
    assigned = service.assign_case(handoff_id=case.handoff_id, assigned_to=operator_id)
    assert assigned.status == HandoffStatus.ASSIGNED
    assert assigned.assigned_to == operator_id

    # Resolve
    resolved = service.resolve_case(
        handoff_id=case.handoff_id,
        status=HandoffStatus.RESOLVED,
        resolved_by=operator_id,
        now=_NOW,
    )
    assert resolved.status == HandoffStatus.RESOLVED
    assert resolved.resolved_at == _NOW

    # No longer open
    assert len(service.list_open_cases()) == 0
