from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.domain.schemas.common import DomainSchema


class ScenarioId(StrEnum):
    SCENARIO_A = "scenario_a_happy_path"
    SCENARIO_B = "scenario_b_asr_quantity_error"
    SCENARIO_C = "scenario_c_ambiguous_customer"
    SCENARIO_D = "scenario_d_stale_quote"
    SCENARIO_E = "scenario_e_inventory_shortage"
    SCENARIO_F = "scenario_f_invoice_failure"
    SCENARIO_G = "scenario_g_dispatch_failure"
    SCENARIO_H = "scenario_h_environment_change"
    SCENARIO_I = "scenario_i_user_correction"
    SCENARIO_J = "scenario_j_product_ambiguity"


class ScenarioDefinition(DomainSchema):
    """Configuration and expected invariant contract for a sandbox scenario."""

    scenario_id: ScenarioId
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    is_approved: bool = False
    faults: dict[str, Any] = Field(default_factory=dict)
    expected_decision: DecisionType
    expected_run_status: VoiceRunStatus
    forbidden_actions: list[str] = Field(default_factory=list)


class ScenarioEvaluationResult(DomainSchema):
    """Result of evaluating one sandbox scenario against safety invariants."""

    scenario_id: ScenarioId
    passed: bool
    run_id: UUID
    actual_decision: str
    actual_status: str
    forbidden_actions_avoided: bool
    details: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class SuiteEvaluationResult(DomainSchema):
    """Aggregated evaluation metrics across the entire A–J benchmark suite."""

    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    safety_violations: int = 0
    false_execution_rate: float = 0.0
    false_confirmation_rate: float = 0.0
    evaluation_timestamp: datetime
    results: list[ScenarioEvaluationResult] = Field(default_factory=list)
