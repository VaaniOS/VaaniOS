from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaaniflow.domain.models.approval import Approval, ApprovalStatus
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
        requested_by: UUID,
        snapshot_version: str,
        order_id: UUID | None = None,
        invoice_id: UUID | None = None,
        now: datetime | None = None,
    ) -> Approval:
        """Create a new approval request bound to the current context snapshot."""
        current_time = now or datetime.now(UTC)
        approval = Approval(
            approval_id=uuid4(),
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
        approved_by: UUID,
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

        if approval.snapshot_version != current_snapshot_version:
            approval.status = ApprovalStatus.EXPIRED
            approval.resolved_at = current_time
            self._repositories.approvals.save(approval=approval)
            return approval

        approval.status = ApprovalStatus.APPROVED
        approval.approved_by = approved_by
        approval.resolved_at = current_time
        self._repositories.approvals.save(approval=approval)
        return approval

    def reject(
        self,
        *,
        approval_id: UUID,
        rejected_by: UUID,
        now: datetime | None = None,
    ) -> Approval:
        """Record explicit rejection of an approval request."""
        approval = self._repositories.approvals.get_by_id(approval_id=approval_id)
        if approval is None:
            raise ValueError(f"Approval request {approval_id} not found.")

        current_time = now or datetime.now(UTC)
        approval.status = ApprovalStatus.REJECTED
        approval.approved_by = rejected_by
        approval.resolved_at = current_time
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
