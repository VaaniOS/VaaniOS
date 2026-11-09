import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated

from fastapi import Depends

from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.handoff.service import HandoffService
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)
from vaaniflow.traces.service import TraceService

# Opt-in demo business clock (ADR-020). Unset: the real clock. "synthetic": the
# synthetic dataset's business time. Otherwise a timezone-aware ISO-8601 instant.
BUSINESS_CLOCK_ENV = "VAANIFLOW_BUSINESS_CLOCK"
SYNTHETIC_CLOCK = "synthetic"


def business_clock_from_env(
    environ: Mapping[str, str] | None = None,
) -> tuple[Callable[[], datetime] | None, str]:
    """
    Resolve the API's business clock from the environment.

    Returns (clock, source). ``clock`` is None when the variable is unset, which
    means the orchestrator uses the real clock. A fixed clock is only ever set
    explicitly; an invalid value fails at startup instead of falling back.
    """
    value = (environ if environ is not None else os.environ).get(BUSINESS_CLOCK_ENV, "").strip()
    if not value:
        return None, "real"
    if value.lower() == SYNTHETIC_CLOCK:
        instant = SYNTHETIC_BUSINESS_TIME
    else:
        try:
            instant = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{BUSINESS_CLOCK_ENV}={value!r} is neither '{SYNTHETIC_CLOCK}' nor an "
                "ISO-8601 timestamp."
            ) from exc
        if instant.tzinfo is None:
            raise ValueError(f"{BUSINESS_CLOCK_ENV}={value!r} must include a timezone offset.")
    return (lambda: instant), f"fixed:{instant.isoformat()}"


class AppContainer:
    """Singleton container of repository and service singletons for API lifespan."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        if clock is None:
            clock, self.business_clock_source = business_clock_from_env()
        else:
            self.business_clock_source = "injected"
        self.repositories = SyntheticRepositories()
        self.orchestrator = VoiceWorkflowOrchestrator(repositories=self.repositories, clock=clock)
        self.runner = EvaluationRunner()
        self.trace_service = TraceService(self.repositories.traces)
        self.handoff_service = HandoffService(self.repositories)


_container: AppContainer | None = None


def get_container() -> AppContainer:
    global _container
    if _container is None:
        _container = AppContainer()
    return _container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def reset_container(clock: Callable[[], datetime] | None = None) -> AppContainer:
    """Reset container with fresh synthetic in-memory state (useful for tests)."""
    global _container
    _container = AppContainer(clock=clock)
    return _container
