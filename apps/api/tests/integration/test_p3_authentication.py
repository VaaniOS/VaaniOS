from uuid import UUID

from fastapi.testclient import TestClient

from tests.auth_support import OPERATOR, OTHER_REQUESTER, REQUESTER, auth, provider
from vaaniflow.api.app import app
from vaaniflow.api.dependencies import AppContainer, reset_container
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
)

client = TestClient(app)
T = SYNTHETIC_BUSINESS_TIME

KUMAR_INSTRUCTION = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
AMBIGUOUS_INSTRUCTION = "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo, parso."
SHARMA_INSTRUCTION = (
    "Sharma Builders ko 200 bags UltraTech cement dispatch karo at the quoted rate."
)


def _fresh_api() -> AppContainer:
    return reset_container(clock=lambda: T, identity_provider=provider())


# =========================================================================== #
# Authenticate /process
# =========================================================================== #


def test_anonymous_user_cannot_supersede_pending_approval() -> None:
    container = _fresh_api()
    headers_a = auth(REQUESTER)

    # 1. User A creates a run and submits an instruction that creates a pending approval
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    res1 = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_INSTRUCTION}, headers=headers_a
    )
    assert res1.status_code == 200
    approval_id = UUID(res1.json()["approval_id"])

    approval = container.repositories.approvals.get_by_id(approval_id=approval_id)
    assert approval is not None and approval.status is ApprovalStatus.REQUESTED

    # 2. Anonymous user tries to send a new instruction to supersede the pending approval
    anon_res = client.post(
        f"/runs/{run_id}/process",
        json={"text": "Different instruction entirely"},
    )
    assert anon_res.status_code == 401
    assert anon_res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"

    # Verify pending approval was NOT superseded
    approval_check = container.repositories.approvals.get_by_id(approval_id=approval_id)
    assert approval_check is not None and approval_check.status is ApprovalStatus.REQUESTED


def test_anonymous_user_cannot_add_instruction_to_existing_run() -> None:
    _fresh_api()
    headers_a = auth(REQUESTER)

    # User A creates a run
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]

    # Anonymous user tries to add an instruction to this existing owned run
    anon_res = client.post(
        f"/runs/{run_id}/process",
        json={"text": KUMAR_INSTRUCTION},
    )
    assert anon_res.status_code == 401
    assert anon_res.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


def test_requester_run_ownership_enforced_on_process() -> None:
    _fresh_api()
    headers_a = auth(REQUESTER)
    headers_b = auth(OTHER_REQUESTER)

    # User A creates a run and processes instruction
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    res_a = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_INSTRUCTION}, headers=headers_a
    )
    assert res_a.status_code == 200

    # User B tries to add instruction to User A's run -> 403 Forbidden
    res_b = client.post(
        f"/runs/{run_id}/process",
        json={"text": "Malicious override by another user"},
        headers=headers_b,
    )
    assert res_b.status_code == 403
    assert res_b.json()["detail"]["code"] == "FORBIDDEN"

    # User A can add instructions to their own run
    res_a_second = client.post(
        f"/runs/{run_id}/process",
        json={"text": KUMAR_INSTRUCTION},
        headers=headers_a,
    )
    assert res_a_second.status_code == 200


def test_operator_can_process_instruction_on_any_run() -> None:
    _fresh_api()
    headers_a = auth(REQUESTER)
    headers_op = auth(OPERATOR)

    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    client.post(f"/runs/{run_id}/process", json={"text": KUMAR_INSTRUCTION}, headers=headers_a)

    # Operator adds an instruction on User A's run -> Allowed
    res_op = client.post(
        f"/runs/{run_id}/process",
        json={"text": KUMAR_INSTRUCTION},
        headers=headers_op,
    )
    assert res_op.status_code == 200


# =========================================================================== #
# Authenticate /clarify
# =========================================================================== #


def test_anonymous_user_cannot_clarify_run() -> None:
    _fresh_api()
    headers_a = auth(REQUESTER)

    # User A creates run requiring clarification (ambiguous product)
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    res = client.post(
        f"/runs/{run_id}/process", json={"text": AMBIGUOUS_INSTRUCTION}, headers=headers_a
    )
    assert res.json()["status"] == "CLARIFICATION_REQUIRED"

    # Anonymous user attempts to clarify -> 401
    anon_clarify = client.post(
        f"/runs/{run_id}/clarify",
        json={"clarification": "UltraTech cement"},
    )
    assert anon_clarify.status_code == 401
    assert anon_clarify.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


def test_unauthorized_user_cannot_alter_another_users_run_on_clarify() -> None:
    _fresh_api()
    headers_a = auth(REQUESTER)
    headers_b = auth(OTHER_REQUESTER)

    # User A creates run requiring clarification
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    res = client.post(
        f"/runs/{run_id}/process", json={"text": AMBIGUOUS_INSTRUCTION}, headers=headers_a
    )
    assert res.json()["status"] == "CLARIFICATION_REQUIRED"

    # User B attempts to clarify User A's run -> 403 Forbidden
    res_b = client.post(
        f"/runs/{run_id}/clarify",
        json={"clarification": "UltraTech cement"},
        headers=headers_b,
    )
    assert res_b.status_code == 403
    assert res_b.json()["detail"]["code"] == "FORBIDDEN"

    # User A clarifies their own run -> 200 OK
    res_a = client.post(
        f"/runs/{run_id}/clarify",
        json={"clarification": SHARMA_INSTRUCTION},
        headers=headers_a,
    )
    assert res_a.status_code == 200
    assert res_a.json()["decision"] == "APPROVAL_REQUIRED"


def test_clarification_cannot_silently_reopen_escalated_run() -> None:
    container = _fresh_api()
    headers_a = auth(REQUESTER)

    # User A creates a run and escalates it to human handoff
    run_id = client.post("/runs", headers=headers_a).json()["run_id"]
    handoff_res = client.post(
        f"/runs/{run_id}/handoff",
        json={"reason": "Manual operator escalation"},
        headers=auth(OPERATOR),
    )
    assert handoff_res.status_code == 200

    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.status is VoiceRunStatus.HANDOFF

    # Attempting to clarify an escalated run is refused with 409 Conflict (RUN_ESCALATED)
    clarify_res = client.post(
        f"/runs/{run_id}/clarify",
        json={"clarification": "Attempting to reopen an escalated handoff"},
        headers=headers_a,
    )
    assert clarify_res.status_code == 409
    assert clarify_res.json()["detail"]["code"] == "RUN_ESCALATED"

    # Verify run remains in HANDOFF status and was not silently reopened
    refreshed_run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert refreshed_run is not None and refreshed_run.status is VoiceRunStatus.HANDOFF
