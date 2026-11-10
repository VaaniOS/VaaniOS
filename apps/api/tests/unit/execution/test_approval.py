from datetime import UTC, datetime
from uuid import uuid4

import pytest

from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import SYNTHETIC_EVALUATION_OWNER, Principal, Role
from vaaniflow.execution.approval import ApprovalService
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories

_NOW = datetime.now(UTC)
OWNER = Principal(
    principal_id=uuid4(),
    display_name="unit owner",
    roles=[Role.OWNER],
    authentication_method="bearer-token",
)


def test_approval_request_and_grant_flow() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    user_id = uuid4()
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
        actor=OWNER,
        current_snapshot_version=snapshot_v1,
        now=_NOW,
    )
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.approved_by == OWNER.principal_id and approved.approved_actor == OWNER
    assert approved.actor_authenticated is True
    assert approved.resolved_at == _NOW
    assert service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v1
    )


def test_approval_expires_when_snapshot_version_changes_scenario_h() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    user_id = uuid4()
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
        actor=OWNER,
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
    snapshot_v1 = "snapshot-v1"

    approval = service.request_approval(
        run_id=uuid4(),
        requested_by=user_id,
        snapshot_version=snapshot_v1,
        now=_NOW,
    )

    rejected = service.reject(
        approval_id=approval.approval_id,
        actor=OWNER,
        now=_NOW,
    )
    assert rejected.status == ApprovalStatus.REJECTED
    assert rejected.rejected_by == OWNER.principal_id and rejected.rejected_actor == OWNER
    assert not service.is_valid_and_approved(
        approval_id=approval.approval_id, current_snapshot_version=snapshot_v1
    )


def test_approval_missing_raises() -> None:
    repos = SyntheticRepositories()
    service = ApprovalService(repos)

    with pytest.raises(ValueError):
        service.approve(
            approval_id=uuid4(),
            actor=OWNER,
            current_snapshot_version="v1",
        )


def test_synthetic_approver_is_recorded_as_not_authenticated() -> None:
    service = ApprovalService(SyntheticRepositories())
    approval = service.request_approval(run_id=uuid4(), snapshot_version="v1", now=_NOW)
    assert approval.actor_authenticated is False  # nobody approved yet

    approved = service.approve(
        approval_id=approval.approval_id,
        actor=SYNTHETIC_EVALUATION_OWNER,
        current_snapshot_version="v1",
        now=_NOW,
    )
    assert approved.approved_actor is not None and approved.approved_actor.synthetic
    assert approved.actor_authenticated is False
