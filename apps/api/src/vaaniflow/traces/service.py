from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vaaniflow.application.ports.business_data import TraceRepository
from vaaniflow.traces.models import RunTrace, TraceEvent, TraceStage


class TraceService:
    """Service for capturing and querying end-to-end trace events and audit logs."""

    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    def record_stage(
        self,
        *,
        run_id: UUID,
        stage: TraceStage,
        component: str | None = None,
        input_ref: str | None = None,
        output_summary: str | None = None,
        confidence: float | None = None,
        decision: str | None = None,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            run_id=run_id,
            stage=stage,
            timestamp=timestamp or datetime.now(UTC),
            latency_ms=latency_ms,
            component=component,
            input_ref=input_ref,
            output_summary=output_summary,
            confidence=confidence,
            decision=decision,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            error_code=error_code,
            error_message=error_message,
            metadata=metadata or {},
        )
        self._repository.record_event(event=event)
        return event

    def get_run_trace(self, *, run_id: UUID) -> RunTrace | None:
        """Retrieve full trace timeline for a run."""
        return self._repository.get_trace(run_id=run_id)

    def list_all_traces(self) -> list[RunTrace]:
        """List all traces across all runs."""
        return self._repository.list_all_traces()
