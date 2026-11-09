from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.traces.models import TraceStage
from vaaniflow.traces.service import TraceService


def test_trace_recording_and_retrieval() -> None:
    repos = SyntheticRepositories()
    service = TraceService(repos.traces)
    run_id = uuid4()
    t1 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 20, 10, 0, 1, tzinfo=UTC)

    # 1. Record stage 1
    ev1 = service.record_stage(
        run_id=run_id,
        stage=TraceStage.INGESTED,
        component="IngestService",
        output_summary="Audio ingested",
        latency_ms=50,
        timestamp=t1,
    )
    assert ev1.stage == TraceStage.INGESTED
    assert ev1.run_id == run_id

    # 2. Record stage 2
    ev2 = service.record_stage(
        run_id=run_id,
        stage=TraceStage.COMPLETED,
        component="Orchestrator",
        output_summary="Workflow completed",
        latency_ms=150,
        timestamp=t2,
    )
    assert ev2.stage == TraceStage.COMPLETED

    # 3. Retrieve trace
    trace = service.get_run_trace(run_id=run_id)
    assert trace is not None
    assert trace.run_id == run_id
    assert len(trace.events) == 2
    assert trace.total_latency_ms == 200
    assert trace.started_at == t1
    assert trace.completed_at == t2


def test_trace_missing_run_returns_none() -> None:
    repos = SyntheticRepositories()
    service = TraceService(repos.traces)
    assert service.get_run_trace(run_id=uuid4()) is None
