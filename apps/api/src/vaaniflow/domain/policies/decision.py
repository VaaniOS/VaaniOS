from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class DecisionType(StrEnum):
    """
    Final action decision produced by the deterministic policy boundary.
    """

    EXECUTE = "EXECUTE"
    CONFIRM = "CONFIRM"
    CLARIFY = "CLARIFY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    BLOCKED = "BLOCKED"


class DecisionReasonCode(StrEnum):
    """
    Machine-readable reason for a policy decision.
    """

    VALIDATED_LOW_RISK = "VALIDATED_LOW_RISK"

    AMBIGUOUS_INPUT = "AMBIGUOUS_INPUT"
    MISSING_INFORMATION = "MISSING_INFORMATION"

    HIGH_RISK_ACTION = "HIGH_RISK_ACTION"
    FINANCIAL_ACTION = "FINANCIAL_ACTION"

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"

    POLICY_VIOLATION = "POLICY_VIOLATION"

    CONFLICTING_BUSINESS_DATA = "CONFLICTING_BUSINESS_DATA"
    TOOL_FAILURE = "TOOL_FAILURE"

    HIGH_FINANCIAL_EXPOSURE = "HIGH_FINANCIAL_EXPOSURE"
    IRREVERSIBLE_ACTION = "IRREVERSIBLE_ACTION"

    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class Decision(DomainSchema):
    """
    Deterministic policy decision for a voice workflow.

    The decision layer is the boundary between:
        agent proposal
    and:
        consequential execution.

    An LLM may propose an action, but it must not bypass this decision.
    """

    decision_id: UUID

    run_id: UUID

    decision: DecisionType

    reason_code: DecisionReasonCode

    reason: str = Field(min_length=1)

    allowed: bool

    requires_user_confirmation: bool = False
    requires_approval: bool = False
    requires_human_handoff: bool = False

    policy_version: str = Field(min_length=1)