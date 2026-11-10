from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from vaaniflow.api.auth import PrincipalDep
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
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import Role
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus
from vaaniflow.execution.service import OperatorResolutionError

router = APIRouter(prefix="/runs", tags=["Runs"])

_APPROVAL_ERROR_STATUS = {
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


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    container: ContainerDep,
    payload: CreateRunRequest | None = None,
    principal: PrincipalDep = None,
) -> CreateRunResponse:
    owner_id = principal.principal_id if principal else None
    run = container.orchestrator.start_run(owner_id=owner_id)
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
        "owner_id": str(run.owner_id) if run.owner_id else None,
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "failure_code": run.failure_code,
        "failure_message": run.failure_message,
    }


def _has_pending_approval(container: AppContainer, run: VoiceRun) -> bool:
    if run.status is VoiceRunStatus.APPROVAL_REQUIRED:
        return True
    if hasattr(container.repositories, "pending_executions"):
        for pending in container.repositories.pending_executions.list_by_run(run_id=run.run_id):
            approval = container.repositories.approvals.get_by_id(approval_id=pending.approval_id)
            if approval is not None and approval.status is ApprovalStatus.REQUESTED:
                return True
    return False


@router.post("/{run_id}/process", response_model=WorkflowResponse)
def process_run(
    run_id: UUID,
    payload: ProcessRunRequest,
    container: ContainerDep,
    principal: PrincipalDep = None,
) -> WorkflowResponse:
    text = payload.text
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Instruction text must be provided for processing.",
        )

    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found.",
        )

    # 1. Prevent anonymous users from superseding an existing pending approval
    if _has_pending_approval(container, run) and principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Anonymous users are not permitted to supersede an existing pending approval.",
            },
        )

    # 2. Require an authenticated principal when adding an instruction to an existing run
    is_existing_active_run = (
        run.owner_id is not None
        or run.status is not VoiceRunStatus.CREATED
        or run.transcript_id is not None
    )
    if is_existing_active_run and principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authenticated principal required when adding an instruction to an existing run.",
            },
        )

    # 3. Enforce requester/run ownership
    if principal is not None:
        if run.owner_id is None:
            run.owner_id = principal.principal_id
            container.repositories.runs.save(run=run)
        elif run.owner_id != principal.principal_id and principal.role not in (
            Role.ADMIN,
            Role.OPERATOR,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": "Principal is not authorized to alter this run; requester ownership violation.",
                },
            )

    result = container.orchestrator.process_text(text=text, run_id=run_id)
    return _to_response(result)


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
    """Approve one pending approval of this run and execute exactly its stored plan."""
    try:
        result = container.orchestrator.approve(
            run_id=run_id,
            approval_id=payload.approval_id,
            approved_by=payload.approved_by,
        )
    except ApprovalFlowError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.post("/{run_id}/reject", response_model=WorkflowResponse)
def reject_run(
    run_id: UUID,
    payload: RejectRequest,
    container: ContainerDep,
) -> WorkflowResponse:
    """Reject one pending approval of this run; its plan can never execute."""
    try:
        result = container.orchestrator.reject(
            run_id=run_id,
            approval_id=payload.approval_id,
            rejected_by=payload.rejected_by,
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
    principal: PrincipalDep = None,
) -> WorkflowResponse:
    run = container.repositories.runs.get_by_id(run_id=run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    # 1. Do not allow clarification to silently reopen an escalated run
    if run.status is VoiceRunStatus.HANDOFF:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RUN_ESCALATED",
                "message": f"Run {run_id} has been escalated to human handoff and cannot be clarified without operator resolution.",
            },
        )

    # 2. Require authentication + appropriate authorization
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication required to clarify a run.",
            },
        )

    # 3. Anonymous users (and unauthorized users) must not be able to reopen or alter another user's run
    if (
        run.owner_id is not None
        and run.owner_id != principal.principal_id
        and principal.role
        not in (
            Role.ADMIN,
            Role.OPERATOR,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Principal is not authorized to alter another user's run.",
            },
        )

    if run.owner_id is None:
        run.owner_id = principal.principal_id
        container.repositories.runs.save(run=run)

    # Resume with clarified text. Any approval still pending on this run is
    # superseded; the response carries the new approval_id if one is requested.
    result = container.orchestrator.process_text(
        text=payload.clarification,
        run_id=run_id,
    )
    return _to_response(result)


@router.post("/{run_id}/confirm", response_model=WorkflowResponse)
def confirm_run(
    run_id: UUID,
    payload: ConfirmRequest,
    container: ContainerDep,
) -> WorkflowResponse:
    """Answer the confirmation pending on this run. Never approves or executes."""
    try:
        result = container.orchestrator.confirm(
            run_id=run_id,
            reply=payload.reply,
            confirmation_id=payload.confirmation_id,
            confirmed_by=payload.confirmed_by,
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
) -> WorkflowResponse:
    """Operator resolution of one UNKNOWN execution, verified against business state."""
    try:
        result = container.orchestrator.resolve_unknown(
            run_id=run_id,
            execution_id=execution_id,
            attempt=payload.attempt,
            outcome=ToolExecutionStatus(payload.outcome),
            reason=payload.reason,
            resolved_by=payload.resolved_by,
            entity_id=payload.entity_id,
        )
    except OperatorResolutionError as error:
        raise _approval_http_error(error) from error
    return _to_response(result)


@router.get("/{run_id}/audit")
def get_run_audit(run_id: UUID, container: ContainerDep) -> dict[str, Any]:
    """End-to-end audit trail of the run, assembled from stored records."""
    audit = RunAuditService(container.repositories).build(run_id=run_id)
    if audit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return audit


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
