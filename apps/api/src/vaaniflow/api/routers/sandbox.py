from fastapi import APIRouter, HTTPException, status

from vaaniflow.api.dependencies import ContainerDep
from vaaniflow.evaluation.models import (
    ScenarioDefinition,
    ScenarioEvaluationResult,
    SuiteEvaluationResult,
)
from vaaniflow.evaluation.scenarios import get_scenario, list_all_scenarios

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])


@router.get("/scenarios", response_model=list[ScenarioDefinition])
def list_scenarios() -> list[ScenarioDefinition]:
    """List all available A–J evaluation scenarios."""
    return list_all_scenarios()


@router.post("/scenarios/{scenario_id}/run", response_model=ScenarioEvaluationResult)
def run_scenario(
    scenario_id: str,
    container: ContainerDep,
) -> ScenarioEvaluationResult:
    """Run an isolated sandbox scenario with controlled fault injection."""
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found.",
        )

    # Use fresh repositories for test isolation
    return container.runner.run_scenario(scenario)


@router.post("/evaluate-all", response_model=SuiteEvaluationResult)
def evaluate_all(
    container: ContainerDep,
) -> SuiteEvaluationResult:
    """Run all 10 canonical scenarios and evaluate safety and accuracy metrics."""
    return container.runner.run_all()
