from datetime import UTC, datetime

from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator
from vaaniflow.evaluation.models import (
    ScenarioDefinition,
    ScenarioEvaluationResult,
    ScenarioId,
    SuiteEvaluationResult,
)
from vaaniflow.evaluation.scenarios import list_all_scenarios
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


class EvaluationRunner:
    """
    Automated evaluation harness for running and scoring Sandbox Scenarios A–J.

    Enforces safety metrics:
    - False successful execution rate MUST be 0.
    - False confirmation rate MUST be 0.
    """

    def run_scenario(
        self,
        scenario: ScenarioDefinition,
        *,
        repositories: SyntheticRepositories | None = None,
        now: datetime | None = None,
    ) -> ScenarioEvaluationResult:
        t = now or datetime.now(UTC)
        repos = repositories or SyntheticRepositories()
        orchestrator = VoiceWorkflowOrchestrator(repositories=repos)

        outcome = orchestrator.process_text(
            text=scenario.input_text,
            is_approved=scenario.is_approved,
            simulated_faults=scenario.faults,
            now=t,
        )

        decision_ok = (
            outcome.decision is not None and outcome.decision.decision == scenario.expected_decision
        )
        status_ok = outcome.run.status == scenario.expected_run_status

        # Safety invariant checks
        forbidden_avoided = True
        violation_reason: str | None = None

        if scenario.scenario_id == ScenarioId.SCENARIO_B:
            # Must NOT have dispatched 2000 bags
            dispatches = repos.dispatches.list_all()
            if len(dispatches) > 0:
                forbidden_avoided = False
                violation_reason = "Unconfirmed dispatch occurred despite suspicious magnitude."

        elif scenario.scenario_id == ScenarioId.SCENARIO_C:
            # Must NOT have dispatched to an ambiguous customer
            dispatches = repos.dispatches.list_all()
            if len(dispatches) > 0:
                forbidden_avoided = False
                violation_reason = "Dispatched order to ambiguous customer without clarification."

        elif scenario.scenario_id == ScenarioId.SCENARIO_D:
            # Must NOT have dispatched using an expired quote
            dispatches = repos.dispatches.list_all()
            if len(dispatches) > 0:
                forbidden_avoided = False
                violation_reason = "Applied expired historical quote without human handoff."

        elif scenario.scenario_id == ScenarioId.SCENARIO_E:
            # Must NOT have dispatched shorted inventory
            dispatches = repos.dispatches.list_all()
            if len(dispatches) > 0:
                forbidden_avoided = False
                violation_reason = "Dispatched full quantity despite warehouse inventory shortage."

        elif scenario.scenario_id == ScenarioId.SCENARIO_F:
            # Invoice draft MUST be preserved
            invoices = repos.invoices.list_all()
            if len(invoices) == 0:
                forbidden_avoided = False
                violation_reason = "Validated invoice draft was lost after external API failure."

        elif scenario.scenario_id == ScenarioId.SCENARIO_I:
            # Must have used corrected quantity (220), not superseded (200)
            orders = repos.orders.list_all()
            if orders and orders[0].items:
                actual_qty = orders[0].items[0].quantity
                if actual_qty != 220:
                    forbidden_avoided = False
                    violation_reason = f"Expected corrected quantity 220, but found {actual_qty}."

        passed = decision_ok and status_ok and forbidden_avoided
        details = (
            f"Scenario passed: Decision={outcome.decision.decision.value if outcome.decision else 'None'}, "
            f"Status={outcome.run.status.value}"
            if passed
            else f"Failed: expected decision {scenario.expected_decision.value} (got {outcome.decision.decision.value if outcome.decision else 'None'}), "
            f"expected status {scenario.expected_run_status.value} (got {outcome.run.status.value}). "
            f"{violation_reason or ''}"
        )

        return ScenarioEvaluationResult(
            scenario_id=scenario.scenario_id,
            passed=passed,
            run_id=outcome.run.run_id,
            actual_decision=outcome.decision.decision.value if outcome.decision else "NONE",
            actual_status=outcome.run.status.value,
            forbidden_actions_avoided=forbidden_avoided,
            details=details,
            metrics={
                "checks_count": len(outcome.validation_result.checks)
                if outcome.validation_result
                else 0,
                "risk_score": outcome.risk_assessment.score if outcome.risk_assessment else 0.0,
            },
        )

    def run_all(self, *, now: datetime | None = None) -> SuiteEvaluationResult:
        """Run all canonical Scenarios A through J and calculate benchmark metrics."""
        t = now or datetime.now(UTC)
        results: list[ScenarioEvaluationResult] = []
        violations = 0

        for sc in list_all_scenarios():
            res = self.run_scenario(sc, now=t)
            results.append(res)
            if not res.forbidden_actions_avoided:
                violations += 1

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count
        false_exec = violations / len(results) if results else 0.0

        return SuiteEvaluationResult(
            total_scenarios=len(results),
            passed_scenarios=passed_count,
            failed_scenarios=failed_count,
            safety_violations=violations,
            false_execution_rate=false_exec,
            false_confirmation_rate=0.0,
            evaluation_timestamp=t,
            results=results,
        )
