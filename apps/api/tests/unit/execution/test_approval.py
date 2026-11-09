from datetime import UTC, datetime
from uuid import uuid4

import pytest

from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.execution.approval import ApprovalService
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories

_NOW = datetime.now(UTC)


def test_approval_request_and_grant_flow() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    user_id = uuid4()
    owner_id = uuid4()
    order_id = uuid4()
    snapshot_v1 = "snapshot-v1-hash-12345"

    # 1. Request approval
    approval = service.request_approval(
        run_id=uuid4(),
        requested_by=user_id,
        snapshot_version=snapshot_v1,
        order_id=order_id,
        now=_NOW,
    )
    assert approval.status == ApprovalStatus.REQUESTED
    assert approval.snapshot_version == snapshot_v1
    assert approval.order_id == order_id

    # Not approved yet
    assert not service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v1
    )

    # 2. Grant approval
    approved = service.approve(
        approval_id=approval.approval_id,
        approved_by=owner_id,
        current_snapshot_version=snapshot_v1,
        now=_NOW,
    )
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_by == owner_id
    assert approved.resolved_at == _NOW
    assert service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v1
    )


def test_approval_expires_when_snapshot_version_changes_scenario_h() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    user_id = uuid4()
    owner_id = uuid4()
    snapshot_v1 = "snapshot-v1-hash-12345"
    snapshot_v2 = "snapshot-v2-hash-changed"  # Price or stock changed!

    approval = service.request_approval(
        run_id=uuid4(),
        requested_by=user_id,
        snapshot_version=snapshot_v1,
        now=_NOW,
    )

    # Approving with stale/changed snapshot
    expired = service.approve(
        approval_id=approval.approval_id,
        approved_by=owner_id,
        current_snapshot_version=snapshot_v2,
        now=_NOW,
    )
    assert expired.status == ApprovalStatus.EXPIRED
    assert not service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v2
    )


def test_approval_rejection_flow() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    user_id = uuid4()
    owner_id = uuid4()
    snapshot_v1 = "snapshot-v1"

    approval = service.request_approval(
        run_id=uuid4(),
        requested_by=user_id,
        snapshot_version=snapshot_v1,
        now=_NOW,
    )

    rejected = service.reject(
        approval_id=approval.approval_id,
        rejected_by=owner_id,
        now=_NOW,
    )
    assert rejected.status == ApprovalStatus.REJECTED
    assert not service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v1
    )


def test_approval_missing_raises() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    with pytest.raises(ValueError):
        service.approve(
            approval_id=uuid4(),
            approved_by=uuid4(),
            current_snapshot_version="v1",
        )
