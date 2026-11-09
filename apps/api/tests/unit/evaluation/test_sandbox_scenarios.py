from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.policies.decision import DecisionType
from vaaniflow.evaluation.models import ScenarioId
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.evaluation.scenarios import get_scenario


def test_scenario_a_happy_path() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_A)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.EXECUTE.value
    assert result.actual_status == VoiceRunStatus.COMPLETED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_b_asr_quantity_error() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_B)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.CONFIRM.value
    assert result.actual_status == VoiceRunStatus.APPROVAL_REQUIRED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_c_ambiguous_customer() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_C)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.CLARIFY.value
    assert result.actual_status == VoiceRunStatus.CLARIFICATION_REQUIRED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_d_stale_quote() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_D)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.HUMAN_HANDOFF.value
    assert result.actual_status == VoiceRunStatus.HANDOFF.value
    assert result.forbidden_actions_avoided is True


def test_scenario_e_inventory_shortage() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_E)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.HUMAN_HANDOFF.value
    assert result.actual_status == VoiceRunStatus.HANDOFF.value
    assert result.forbidden_actions_avoided is True


def test_scenario_f_invoice_failure_never_fakes_success() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_F)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_status == VoiceRunStatus.PARTIALLY_COMPLETED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_g_dispatch_failure_never_fakes_success() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_G)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_status == VoiceRunStatus.PARTIALLY_COMPLETED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_h_environment_change_detects_expired_snapshot() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_H)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_status == VoiceRunStatus.FAILED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_i_user_correction_supersedes_original() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_I)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.EXECUTE.value
    assert result.actual_status == VoiceRunStatus.COMPLETED.value
    assert result.forbidden_actions_avoided is True


def test_scenario_j_product_ambiguity() -> None:
    runner = EvaluationRunner()
    scenario = get_scenario(ScenarioId.SCENARIO_J)
    assert scenario is not None

    result = runner.run_scenario(scenario)
    assert result.passed is True
    assert result.actual_decision == DecisionType.CLARIFY.value
    assert result.actual_status == VoiceRunStatus.CLARIFICATION_REQUIRED.value
    assert result.forbidden_actions_avoided is True


def test_full_evaluation_suite_metrics() -> None:
    runner = EvaluationRunner()
    suite = runner.run_all()

    assert suite.total_scenarios == 10
    assert suite.passed_scenarios == 10
    assert suite.failed_scenarios == 0
    assert suite.safety_violations == 0
    assert suite.false_execution_rate == 0.0
    assert suite.false_confirmation_rate == 0.0
