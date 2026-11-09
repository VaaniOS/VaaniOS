from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from vaaniflow.api.dependencies import ContainerDep
from vaaniflow.api.schemas import (
    ApproveRequest,
    ClarifyRequest,
    CreateRunRequest,
    CreateRunResponse,
    ManualHandoffRequest,
    ProcessRunRequest,
    WorkflowResponse,
)
from vaaniflow.domain.models.voice_run import VoiceRunStatus

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    container: ContainerDep,
    payload: CreateRunRequest | None = None,
) -> CreateRunResponse:
    run = container.orchestrator.start_run()
    if payload and payload.text:
        container.orchestrator.process_text(text=payload.text, run_id=run.run_id)
        refreshed = container.repositories.runs.get_by_id(run_id=run.run_id)
        if refreshed:
            run = refreshed

    return CreateRunResponse(
        run_id=run.run_id,
        status=run.status,
        created_at=run.created_at,
    )


@router.get("/{run_id}")
def get_run(
    run_id: UUID,
    container: ContainerDep,
) -> dict:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found.",
        )
    return {
        "run_id": str(run.run_id),
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "failure_code": run.failure_code,
        "failure_message": run.failure_message,
    }


@router.post("/{run_id}/process", response_model=WorkflowResponse)
def process_run(
    run_id: UUID,
    payload: ProcessRunRequest,
    container: ContainerDep,
) -> WorkflowResponse:
    text = payload.text
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instruction text must be provided for processing.",
        )

    result = container.orchestrator.process_text(
        text=text,
        run_id=run_id,
        is_approved=payload.is_approved,
        approved_by=payload.approved_by,
        simulated_faults=payload.faults,
    )

    return WorkflowResponse(
        run_id=result.run.run_id,
        status=result.run.status,
        message=result.message,
        decision=result.decision.decision if result.decision else None,
        decision_reason=result.decision.reason if result.decision else None,
        snapshot_version=result.snapshot_version,
        approval_required=bool(result.approval),
        approval_id=result.approval.approval_id if result.approval else None,
        handoff_case_id=result.handoff_case.handoff_id if result.handoff_case else None,
        execution_success=result.execution_outcome.success if result.execution_outcome else None,
    )


@router.get("/{run_id}/trace")
def get_run_trace(
    run_id: UUID,
    container: ContainerDep,
) -> dict:
    trace = container.trace_service.get_run_trace(run_id=run_id)
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace for run {run_id} not found.",
        )
    return {
        "run_id": str(trace.run_id),
        "total_latency_ms": trace.total_latency_ms,
        "started_at": trace.started_at.isoformat(),
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        "events": [
            {
                "event_id": str(e.event_id),
                "stage": e.stage.value,
                "timestamp": e.timestamp.isoformat(),
                "latency_ms": e.latency_ms,
                "output_summary": e.output_summary,
                "decision": e.decision,
                "error_code": e.error_code,
                "error_message": e.error_message,
            }
            for e in trace.events
        ],
    }


@router.get("/{run_id}/validation")
def get_run_validation(
    run_id: UUID,
    container: ContainerDep,
) -> dict:
    trace = container.trace_service.get_run_trace(run_id=run_id)
    if not trace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    validated_event = next((e for e in trace.events if e.stage.value == "VALIDATED"), None)
    risk_event = next((e for e in trace.events if e.stage.value == "RISK_ASSESSED"), None)

    return {
        "run_id": str(run_id),
        "validation_summary": validated_event.output_summary if validated_event else None,
        "risk_summary": risk_event.output_summary if risk_event else None,
        "risk_score": risk_event.confidence if risk_event else None,
    }


@router.post("/{run_id}/approve", response_model=WorkflowResponse)
def approve_run(
    run_id: UUID,
    payload: ApproveRequest,
    container: ContainerDep,
) -> WorkflowResponse:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    # Re-process with explicit approval granted
    result = container.orchestrator.process_text(
        text="Send 200 bags of UltraTech cement to Sharma Builders at the rate quoted day before yesterday and dispatch.",
        run_id=run_id,
        is_approved=True,
        approved_by=payload.approved_by or uuid4(),
    )

    return WorkflowResponse(
        run_id=result.run.run_id,
        status=result.run.status,
        message=result.message,
        decision=result.decision.decision if result.decision else None,
        decision_reason=result.decision.reason if result.decision else None,
        execution_success=result.execution_outcome.success if result.execution_outcome else None,
    )


@router.post("/{run_id}/clarify", response_model=WorkflowResponse)
def clarify_run(
    run_id: UUID,
    payload: ClarifyRequest,
    container: ContainerDep,
) -> WorkflowResponse:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    # Resume with clarified text
    result = container.orchestrator.process_text(
        text=payload.clarification,
        run_id=run_id,
    )

    return WorkflowResponse(
        run_id=result.run.run_id,
        status=result.run.status,
        message=result.message,
        decision=result.decision.decision if result.decision else None,
        decision_reason=result.decision.reason if result.decision else None,
        execution_success=result.execution_outcome.success if result.execution_outcome else None,
    )


@router.post("/{run_id}/handoff")
def create_manual_handoff(
    run_id: UUID,
    payload: ManualHandoffRequest,
    container: ContainerDep,
) -> dict:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    case = container.handoff_service.create_case(
        run_id=run_id,
        reason=payload.reason,
        original_request="Manual operator escalation",
    )
    if payload.operator_id:
        case = container.handoff_service.assign_case(
            handoff_id=case.handoff_id, assigned_to=payload.operator_id
        )

    run.status = VoiceRunStatus.HANDOFF
    container.repositories.runs.save(run=run)

    return {
        "handoff_id": str(case.handoff_id),
        "run_id": str(case.run_id),
        "status": case.status.value,
        "priority": case.priority.value,
        "reason": case.reason,
    }
