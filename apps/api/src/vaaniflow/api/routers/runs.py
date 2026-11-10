from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from vaaniflow.api.auth import (
    ApproverDep,
    AuditorDep,
    AuthenticatedDep,
    ConfirmerDep,
    EscalatorDep,
    InstructorDep,
    ResolverDep,
    authorization_http_error,
)
from vaaniflow.api.dependencies import AppContainer, ContainerDep
from vaaniflow.api.schemas import (
    ApproveRequest,
    ClarificationView,
    ClarifyRequest,
    ConfirmationView,
    ConfirmRequest,
    CreateRunRequest,
    CreateRunResponse,
    DuplicateView,
    ManualHandoffRequest,
    ProcessRunRequest,
    RejectRequest,
    ResolveUnknownRequest,
    WorkflowResponse,
)
from vaaniflow.application.services.audit import RunAuditService
from vaaniflow.application.services.orchestrator import ApprovalFlowError, WorkflowResult
from vaaniflow.application.services.run_access import authorize_instruction, authorize_run_read
from vaaniflow.domain.models.principal import AuthorizationError, Principal
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus
from vaaniflow.execution.service import OperatorResolutionError

router = APIRouter(prefix="/runs", tags=["Runs"])

_APPROVAL_ERROR_STATUS = {
    "UNAUTHENTICATED": status.HTTP_401_UNAUTHORIZED,
    "FORBIDDEN": status.HTTP_403_FORBIDDEN,
    "RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "APPROVAL_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "APPROVAL_RUN_MISMATCH": status.HTTP_409_CONFLICT,
    "APPROVAL_NOT_PENDING": status.HTTP_409_CONFLICT,
    "APPROVAL_SUPERSEDED": status.HTTP_409_CONFLICT,
    "CONFIRMATION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "CONFIRMATION_RUN_MISMATCH": status.HTTP_409_CONFLICT,
    "CONFIRMATION_NOT_PENDING": status.HTTP_409_CONFLICT,
    "CONFIRMATION_SUPERSEDED": status.HTTP_409_CONFLICT,
    "EXECUTION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "EXECUTION_RUN_MISMATCH": status.HTTP_409_CONFLICT,
    "NOT_UNKNOWN": status.HTTP_409_CONFLICT,
    "ALREADY_RESOLVED": status.HTTP_409_CONFLICT,
    "STALE_RESOLUTION": status.HTTP_409_CONFLICT,
    "RESOLUTION_NOT_VERIFIED": status.HTTP_409_CONFLICT,
    "RESOLUTION_CONTRADICTED": status.HTTP_409_CONFLICT,
    "NO_VERIFICATION_CONTRACT": status.HTTP_409_CONFLICT,
    "INVALID_RESOLUTION": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _to_response(result: WorkflowResult) -> WorkflowResponse:
    understand = result.understand_result
    plan = result.plan
    return WorkflowResponse(
        run_id=result.run.run_id,
        status=result.run.status,
        message=result.message,
        decision=result.decision.decision if result.decision else None,
        decision_reason=result.decision.reason if result.decision else None,
        snapshot_version=result.snapshot_version,
        approval_required=result.run.status is VoiceRunStatus.APPROVAL_REQUIRED
        and result.approval is not None,
        approval_id=result.approval.approval_id if result.approval else None,
        handoff_case_id=result.handoff_case.handoff_id if result.handoff_case else None,
        execution_success=(
            result.all_steps_verified
            if result.step_outcomes
            else (result.execution_outcome.success if result.execution_outcome else None)
        ),
        actionability=understand.actionability.value if understand else None,
        evaluation_reasons=list(understand.evaluation.reasons) if understand else [],
        ambiguities=list(understand.semantic_state.ambiguities) if understand else [],
        planned_tools=plan.tool_names if plan else [],
        unsupported_actions=[a.value for a in plan.unsupported_actions] if plan else [],
        excluded_negated_actions=[a.value for a in plan.excluded_negated_actions] if plan else [],
        executed_tools=result.executed_tools,
        tool_outcomes=list(result.step_outcomes),
        superseded_approval_ids=list(result.superseded_approval_ids),
        superseded_confirmation_ids=list(result.superseded_confirmation_ids),
        superseded_clarification_ids=list(result.superseded_clarification_ids),
        confirmation=ConfirmationView(
            confirmation_id=result.confirmation.confirmation_id,
            status=result.confirmation.status.value,
            prompt=result.confirmation.prompt,
            warnings=result.confirmation.warnings,
        )
        if result.confirmation
        else None,
        clarification=ClarificationView(
            clarification_id=result.clarification.clarification_id,
            reason_code=result.clarification.reason_code,
            reason=result.clarification.reason,
            unresolved=result.clarification.unresolved,
            understood=result.clarification.understood,
        )
        if result.clarification
        else None,
        duplicate_check=DuplicateView(
            status=result.duplicate_check.status.value,
            reason=result.duplicate_check.reason,
            duplicate_order_ids=result.duplicate_check.duplicate_order_ids,
        )
        if result.duplicate_check
        else None,
    )


def _approval_http_error(error: ApprovalFlowError | OperatorResolutionError) -> HTTPException:
    return HTTPException(
        status_code=_APPROVAL_ERROR_STATUS.get(error.code, status.HTTP_409_CONFLICT),
        detail={"code": error.code, "message": error.message},
    )


def _run_or_404(container: AppContainer, run_id: UUID) -> VoiceRun:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found."
        )
    return run


def _readable_run(container: AppContainer, run_id: UUID, principal: Principal) -> VoiceRun:
    run = _run_or_404(container, run_id)
    try:
        authorize_run_read(principal, run)
    except AuthorizationError as error:
        raise authorization_http_error(error) from error
    return run


def _instructable_run(container: AppContainer, run_id: UUID, principal: Principal) -> VoiceRun:
    """The run, if ``principal`` may add an instruction to it (ownership, run state)."""
    run = _run_or_404(container, run_id)
    try:
        authorize_instruction(principal, run)
    except AuthorizationError as error:
        raise authorization_http_error(error) from error
    if run.owner_id is None:
        # A run created without an owner is claimed by its first authenticated instructor.
        run.owner_id = principal.principal_id
        container.repositories.runs.save(run=run)
    return run


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    container: ContainerDep,
    principal: InstructorDep,
    payload: CreateRunRequest | None = None,
) -> CreateRunResponse:
    """Create a run owned by the authenticated principal (optionally with an instruction)."""
    run = container.orchestrator.start_run(owner_id=principal.principal_id)
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
    principal: AuthenticatedDep,
) -> dict:
    run = _readable_run(container, run_id, principal)
    return {
        "run_id": str(run.run_id),
        "owner_id": str(run.owner_id) if run.owner_id else None,
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
    principal: InstructorDep,
) -> WorkflowResponse:
    text = payload.text
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instruction text must be provided for processing.",
        )
    _instructable_run(container, run_id, principal)
    result = container.orchestrator.process_text(text=text, run_id=run_id)
    return _to_response(result)


@router.get("/{run_id}/trace")
def get_run_trace(
    run_id: UUID,
    container: ContainerDep,
    principal: AuthenticatedDep,
) -> dict:
    _readable_run(container, run_id, principal)
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
    principal: AuthenticatedDep,
) -> dict:
    _readable_run(container, run_id, principal)
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
    principal: ApproverDep,
) -> WorkflowResponse:
    """Approve one pending approval of this run and execute exactly its stored plan."""
    try:
        result = container.orchestrator.approve(
            run_id=run_id,
            approval_id=payload.approval_id,
            actor=principal,
        )
    except ApprovalFlowError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.post("/{run_id}/reject", response_model=WorkflowResponse)
def reject_run(
    run_id: UUID,
    payload: RejectRequest,
    container: ContainerDep,
    principal: ApproverDep,
) -> WorkflowResponse:
    """Reject one pending approval of this run; its plan can never execute."""
    try:
        result = container.orchestrator.reject(
            run_id=run_id,
            approval_id=payload.approval_id,
            actor=principal,
            reason=payload.reason,
        )
    except ApprovalFlowError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.post("/{run_id}/clarify", response_model=WorkflowResponse)
def clarify_run(
    run_id: UUID,
    payload: ClarifyRequest,
    container: ContainerDep,
    principal: InstructorDep,
) -> WorkflowResponse:
    """
    Answer the principal's own open run: a short reply is merged into the slots the
    open clarification asked for; a complete instruction replaces the request.
    """
    _instructable_run(container, run_id, principal)
    # Any approval still pending on this run is superseded; the response carries
    # the new approval_id if one is requested.
    result = container.orchestrator.clarify(run_id=run_id, reply=payload.clarification)
    return _to_response(result)


@router.post("/{run_id}/confirm", response_model=WorkflowResponse)
def confirm_run(
    run_id: UUID,
    payload: ConfirmRequest,
    container: ContainerDep,
    principal: ConfirmerDep,
) -> WorkflowResponse:
    """Answer the confirmation pending on this run. Never approves or executes."""
    try:
        result = container.orchestrator.confirm(
            run_id=run_id,
            reply=payload.reply,
            confirmation_id=payload.confirmation_id,
            actor=principal,
        )
    except ApprovalFlowError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.post("/{run_id}/executions/{execution_id}/resolve", response_model=WorkflowResponse)
def resolve_unknown_execution(
    run_id: UUID,
    execution_id: UUID,
    payload: ResolveUnknownRequest,
    container: ContainerDep,
    principal: ResolverDep,
) -> WorkflowResponse:
    """Operator resolution of one UNKNOWN execution, verified against business state."""
    try:
        result = container.orchestrator.resolve_unknown(
            run_id=run_id,
            execution_id=execution_id,
            attempt=payload.attempt,
            outcome=ToolExecutionStatus(payload.outcome),
            reason=payload.reason,
            actor=principal,
            entity_id=payload.entity_id,
        )
    except OperatorResolutionError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.get("/{run_id}/audit")
def get_run_audit(run_id: UUID, container: ContainerDep, principal: AuditorDep) -> dict[str, Any]:
    """End-to-end audit trail of the run, assembled from stored records."""
    audit = RunAuditService(container.repositories).build(run_id=run_id)
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return audit


@router.post("/{run_id}/handoff", response_model=WorkflowResponse)
def create_manual_handoff(
    run_id: UUID,
    payload: ManualHandoffRequest,
    container: ContainerDep,
    principal: EscalatorDep,
) -> WorkflowResponse:
    """Escalate to a human operator: everything pending on the run is superseded first."""
    try:
        result = container.orchestrator.escalate(
            run_id=run_id, reason=payload.reason, actor=principal
        )
    except ApprovalFlowError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)
