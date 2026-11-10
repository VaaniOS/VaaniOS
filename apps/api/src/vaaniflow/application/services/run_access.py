"""
Run-level access rules shared by every adapter (HTTP API now, Telegram later).

Ownership is the authenticated principal that created the run. It is never
taken from a request body or header.
"""

from vaaniflow.domain.models.principal import (
    AuthorizationError,
    Permission,
    Principal,
    Role,
    require_permission,
)
from vaaniflow.domain.models.voice_run import VoiceRun, VoiceRunStatus

# Runs whose outcome is settled. A new instruction would reopen them, so it is
# refused; the caller starts a new run instead.
CLOSED_RUN_STATUSES = frozenset(
    {
        VoiceRunStatus.EXECUTING,
        VoiceRunStatus.COMPLETED,
        VoiceRunStatus.PARTIALLY_COMPLETED,
        VoiceRunStatus.FAILED,
        VoiceRunStatus.BLOCKED,
    }
)


def authorize_instruction(principal: Principal | None, run: VoiceRun) -> Principal:
    """
    May ``principal`` add an instruction to ``run``?

    Requires SUBMIT_INSTRUCTION; the run must be the principal's own (an
    OPERATOR may re-instruct any run); escalated and closed runs are refused.
    """
    principal = require_permission(principal, Permission.SUBMIT_INSTRUCTION)
    if run.status is VoiceRunStatus.HANDOFF:
        raise AuthorizationError(
            "RUN_ESCALATED",
            f"Run {run.run_id} has been handed to a human operator; it cannot take new "
            "instructions. Start a new run.",
        )
    if run.status in CLOSED_RUN_STATUSES:
        raise AuthorizationError(
            "RUN_CLOSED",
            f"Run {run.run_id} is {run.status.value}; it cannot take new instructions. "
            "Start a new run.",
        )
    if (
        run.owner_id is not None
        and run.owner_id != principal.principal_id
        and not principal.has_role(Role.OPERATOR)
    ):
        raise AuthorizationError("FORBIDDEN", f"Run {run.run_id} belongs to another principal.")
    return principal


def authorize_run_read(principal: Principal | None, run: VoiceRun) -> Principal:
    """The run's owner, or anyone holding READ_AUDIT, may read its state and trace."""
    if principal is None:
        raise AuthorizationError("UNAUTHENTICATED", "Reading a run requires authentication.")
    if run.owner_id == principal.principal_id or principal.may(Permission.READ_AUDIT):
        return principal
    raise AuthorizationError("FORBIDDEN", f"Run {run.run_id} belongs to another principal.")
