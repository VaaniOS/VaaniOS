from typing import Annotated

from fastapi import Depends

from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.handoff.service import HandoffService
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.traces.service import TraceService


class AppContainer:
    """Singleton container of repository and service singletons for API lifespan."""

    def __init__(self) -> None:
        self.repositories = SyntheticRepositories()
        self.orchestrator = VoiceWorkflowOrchestrator(repositories=self.repositories)
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


def reset_container() -> AppContainer:
    """Reset container with fresh synthetic in-memory state (useful for tests)."""
    global _container
    _container = AppContainer()
    return _container
