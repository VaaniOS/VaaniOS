from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaaniflow.domain.models.approval import Approval, ApprovalStatus
from vaaniflow.domain.models.principal import Principal
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


class ApprovalService:
    """
    Manages explicit human approval for consequential business actions.

    Approvals are cryptographically / deterministically bound to a specific
    business context snapshot_version. If underlying business parameters change,
    approvals expire and must be re-requested.
    """

    def __init__(self, repositories: SyntheticRepositories) -> None:
        self._repositories = repositories

    def request_approval(
        self,
        *,
        run_id: UUID,
        snapshot_version: str,
        requested_by: UUID | None = None,
        plan_id: UUID | None = None,
        plan_fingerprint: str | None = None,
        order_id: UUID | None = None,
        invoice_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """Create a new approval request bound to its run, plan and business snapshot."""
        current_time = now or datetime.now(UTC)
        approval = Approval(
            approval_id=uuid4(),
            run_id=run_id,
            plan_id=plan_id,
            plan_fingerprint=plan_fingerprint,
            order_id=order_id,
            invoice_id=invoice_id,
            requested_by=requested_by,
            status=ApprovalStatus.REQUESTED,
            snapshot_version=snapshot_version,
            requested_at=current_time,
        )
        self._repositories.approvals.save(approval=approval)
        return approval

    def approve(
        self,
        *,
        approval_id: UUID,
        actor: Principal,
        current_snapshot_version: str,
        now: datetime | None = None,
    ) -> Approval:
        """
        Record explicit owner approval.

        If the current snapshot version differs from the snapshot version at request time
        (e.g., inventory or quote changed in the interim), the approval expires immediately.
        """
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found.")

        current_time = now or datetime.now(UTC)

        approval.approved_snapshot_version = current_snapshot_version
        if approval.snapshot_version != current_snapshot_version:
            approval.status = ApprovalStatus.EXPIRED
            approval.expiry_reason = "Business snapshot changed after approval was requested."
            approval.resolved_at = current_time
            self._repositories.approvals.save(approval=approval)
            return approval

        approval.status = ApprovalStatus.APPROVED
        approval.approved_by = actor.principal_id
        approval.approved_actor = actor
        approval.actor_authenticated = not actor.synthetic
        approval.resolved_at = current_time
        self._repositories.approvals.save(approval=approval)
        return approval

    def reject(
        self,
        *,
        approval_id: UUID,
        actor: Principal,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """Record explicit rejection of an approval request."""
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found.")

        current_time = now or datetime.now(UTC)
        approval.status = ApprovalStatus.REJECTED
        approval.rejected_by = actor.principal_id
        approval.rejected_actor = actor
        approval.actor_authenticated = not actor.synthetic
        approval.rejection_reason = reason
        approval.resolved_at = current_time
        self._repositories.approvals.save(approval=approval)
        return approval

    def supersede(self, *, approval_id: UUID, now: datetime | None = None) -> Approval:
        """
        Mark a still-REQUESTED approval SUPERSEDED: a newer instruction on the
        same run replaced it. The record is kept for audit; it can never execute.
        """
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found.")
        if approval.status is not ApprovalStatus.REQUESTED:
            return approval
        approval.status = ApprovalStatus.SUPERSEDED
        approval.resolved_at = now or datetime.now(UTC)
        self._repositories.approvals.save(approval=approval)
        return approval

    def expire(
        self,
        *,
        approval_id: UUID,
        reason: str,
        observed_snapshot_version: str | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """Mark a REQUESTED approval EXPIRED with the reason it can no longer execute."""
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found.")
        approval.approved_snapshot_version = observed_snapshot_version
        approval.status = ApprovalStatus.EXPIRED
        approval.expiry_reason = reason
        approval.resolved_at = now or datetime.now(UTC)
        self._repositories.approvals.save(approval=approval)
        return approval

    def get_approval(self, *, approval_id: UUID) -> Approval | None:
        """Retrieve approval record by ID."""
        return self._repositories.approvals.get_by_id(approval_id=approval_id)

    def is_valid_and_approved(self, *, approval_id: UUID, current_snapshot_version: str) -> bool:
        """Verify that an approval exists, is APPROVED, and snapshot version is still matching."""
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            return False
        return (
            approval.status == ApprovalStatus.APPROVED
            and approval.snapshot_version == current_snapshot_version
        )
