from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vaaniflow.domain.models.handoff import (
    HandoffCase,
    HandoffPriority,
    HandoffStatus,
)
from vaaniflow.domain.models.tool_execution import (
    ToolExecution,
    ToolExecutionStatus,
    ToolSideEffect,
)
from vaaniflow.domain.models.validation import (
    ValidationCheck,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)
from vaaniflow.domain.models.verification import (
    Verification,
    VerificationStatus,
)


def test_validation_result_accepts_valid_contract() -> None:
    validation = ValidationResult(
        validation_id=uuid4(),
        run_id=uuid4(),
        status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                check_id=uuid4(),
                check_type="INVENTORY",
                status=ValidationStatus.PASSED,
                severity=ValidationSeverity.INFO,
                message="Requested quantity is available.",
                field="quantity",
                expected=200,
                actual=200,
                evidence=["inventory:warehouse-1:product-1"],
            )
        ],
        validated_at=datetime.now(UTC),
        validator_version="1.0",
    )

    assert validation.status == ValidationStatus.PASSED
    assert len(validation.checks) == 1


def test_tool_execution_requires_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        ToolExecution(
            execution_id=uuid4(),
            run_id=uuid4(),
            tool_name="create_invoice",
            side_effect=ToolSideEffect.DRAFT,
            status=ToolExecutionStatus.NOT_STARTED,
            idempotency_key="",
            started_at=datetime.now(UTC),
        )


def test_tool_execution_can_represent_unknown_outcome() -> None:
    execution = ToolExecution(
        execution_id=uuid4(),
        run_id=uuid4(),
        tool_name="dispatch_order",
        side_effect=ToolSideEffect.IRREVERSIBLE_WRITE,
        status=ToolExecutionStatus.UNKNOWN,
        idempotency_key="run-123:dispatch:order-456",
        error_code="TIMEOUT",
        error_message="No response received from dispatch provider.",
        started_at=datetime.now(UTC),
    )

    assert execution.status == ToolExecutionStatus.UNKNOWN
    assert execution.side_effect == ToolSideEffect.IRREVERSIBLE_WRITE


def test_verification_can_represent_mismatch() -> None:
    verification = Verification(
        verification_id=uuid4(),
        run_id=uuid4(),
        execution_id=uuid4(),
        status=VerificationStatus.MISMATCH,
        expected_state={"status": "DISPATCHED"},
        actual_state={"status": "PENDING"},
        mismatches=["Dispatch status did not reach DISPATCHED."],
        verifier_version="1.0",
    )

    assert verification.status == VerificationStatus.MISMATCH
    assert len(verification.mismatches) == 1


def test_handoff_preserves_reason_and_recommended_action() -> None:
    handoff = HandoffCase(
        handoff_id=uuid4(),
        run_id=uuid4(),
        status=HandoffStatus.CREATED,
        priority=HandoffPriority.HIGH,
        reason="Multiple customers matched the spoken name.",
        original_request="Send 200 bags to Sharma Builders.",
        interpreted_request={
            "customer_surface": "Sharma Builders",
            "quantity": 200,
        },
        uncertainties=["customer identity"],
        evidence=[
            "customer-match:sharma-builders",
            "customer-match:sharma-buildtech",
        ],
        attempted_actions=["resolve_customer"],
        blocked_actions=["create_dispatch_order"],
        recommended_action="Ask the operator to select the correct customer.",
        risk_summary="Dispatch must not proceed with ambiguous customer identity.",
        created_at=datetime.now(UTC),
    )

    assert handoff.priority == HandoffPriority.HIGH
    assert handoff.status == HandoffStatus.CREATED
    assert handoff.recommended_action is not None


def test_domain_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ToolExecution(
            execution_id=uuid4(),
            run_id=uuid4(),
            tool_name="create_invoice",
            side_effect=ToolSideEffect.DRAFT,
            status=ToolExecutionStatus.NOT_STARTED,
            idempotency_key="run-123:invoice:456",
            started_at=datetime.now(UTC),
            totally_fake_field=True,
        )