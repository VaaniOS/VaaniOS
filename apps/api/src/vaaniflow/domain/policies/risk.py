from enum import StrEnum
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.schemas.common import DomainSchema


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskFactorType(StrEnum):
    SEMANTIC_UNCERTAINTY = "SEMANTIC_UNCERTAINTY"
    ENTITY_AMBIGUITY = "ENTITY_AMBIGUITY"
    FINANCIAL_EXPOSURE = "FINANCIAL_EXPOSURE"
    IRREVERSIBILITY = "IRREVERSIBILITY"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"
    SENSITIVE_DATA = "SENSITIVE_DATA"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TOOL_RELIABILITY = "TOOL_RELIABILITY"
    AUTHORIZATION = "AUTHORIZATION"


class RiskFactor(DomainSchema):
    """
    One factor contributing to the overall action risk.
    """

    factor_id: UUID

    factor_type: RiskFactorType

    level: RiskLevel

    score: float = Field(ge=0.0, le=1.0)

    description: str = Field(min_length=1)


class RiskAssessment(DomainSchema):
    """
    Risk assessment for a proposed business action.

    Risk answers:
        "How dangerous is it to proceed?"

    It does not itself determine whether the action is permitted.
    That decision belongs to the policy layer.
    """

    risk_assessment_id: UUID

    run_id: UUID

    level: RiskLevel

    score: float = Field(ge=0.0, le=1.0)

    factors: list[RiskFactor] = Field(default_factory=list)

    assessor_version: str = Field(min_length=1)
