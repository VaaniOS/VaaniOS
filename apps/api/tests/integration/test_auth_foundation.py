"""
ADR-022 — one verified authentication/authorization model for every adapter.

Identity comes only from a configured bearer token; roles come only from the
token's configured principal. Headers, token naming, request bodies and run
fields never create or elevate an identity.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tests.auth_support import (
    AUDITOR,
    NO_ROLES,
    OPERATOR,
    OTHER_REQUESTER,
    OWNER,
    REQUESTER,
    STAFF,
    auth,
    provider,
)
from vaaniflow.api.app import app
from vaaniflow.api.auth import StaticTokenIdentityProvider
from vaaniflow.api.dependencies import AppContainer, reset_container
from vaaniflow.application.services.orchestrator import ApprovalFlowError
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import Role
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.infrastructure.repositories.synthetic_data import SYNTHETIC_BUSINESS_TIME

client = TestClient(app)
T = SYNTHETIC_BUSINESS_TIME

KUMAR = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
KUMAR_11 = "Kumar Constructions ko 11 bags ACC cement ₹400 per bag dispatch karo."
LARGE = (
    "Sharma Builders ko 2000 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha."
)
AMBIGUOUS = "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo, parso."


def _fresh() -> AppContainer:
    return reset_container(clock=lambda: T, identity_provider=provider())


def _writes(container: AppContainer) -> tuple[int, int, int]:
    repos = container.repositories
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


def _run_with_approval(owner: Any = REQUESTER, text: str = KUMAR) -> tuple[str, str]:
    run_id = client.post("/runs", headers=auth(owner)).json()["run_id"]
    body = client.post(f"/runs/{run_id}/process", json={"text": text}, headers=auth(owner))
    assert body.status_code == 200, body.text
    return run_id, body.json()["approval_id"]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


def test_valid_configured_token_authenticates_as_its_principal() -> None:
    container = _fresh()
    run_id = client.post("/runs", headers=auth(REQUESTER)).json()["run_id"]
    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.owner_id == REQUESTER.principal_id
    assert client.get(f"/runs/{run_id}", headers=auth(REQUESTER)).status_code == 200


def test_invalid_token_is_rejected() -> None:
    _fresh()
    response = client.post("/runs", headers={"Authorization": "Bearer not-a-configured-token"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def _protected_calls(run_id: str, approval_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("post", "/runs", {}),
        ("post", f"/runs/{run_id}/process", {"text": KUMAR}),
        ("post", f"/runs/{run_id}/clarify", {"clarification": KUMAR}),
        ("post", f"/runs/{run_id}/approve", {"approval_id": approval_id}),
        ("post", f"/runs/{run_id}/reject", {"approval_id": approval_id}),
        ("post", f"/runs/{run_id}/confirm", {"reply": "yes"}),
        (
            "post",
            f"/runs/{run_id}/executions/{uuid4()}/resolve",
            {"attempt": 1, "outcome": "FAILED", "reason": "x"},
        ),
        ("post", f"/runs/{run_id}/handoff", {"reason": "x"}),
        ("get", f"/runs/{run_id}", {}),
        ("get", f"/runs/{run_id}/trace", {}),
        ("get", f"/runs/{run_id}/validation", {}),
        ("get", f"/runs/{run_id}/audit", {}),
    ]


def test_missing_credentials_are_rejected_on_every_protected_endpoint() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    for method, path, body in _protected_calls(run_id, approval_id):
        kwargs: dict[str, Any] = {"json": body} if method == "post" else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"
    approval = container.repositories.approvals.get_by_id(approval_id=UUID(approval_id))
    assert approval is not None and approval.status is ApprovalStatus.REQUESTED
    assert _writes(container) == (0, 0, 0)


def test_unset_token_configuration_denies_everyone_and_malformed_fails_closed() -> None:
    reset_container(clock=lambda: T, identity_provider=StaticTokenIdentityProvider.from_env({}))
    assert client.post("/runs", headers=auth(OWNER)).status_code == 401
    for raw in [
        "not json",
        (
            '{"short": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x",'
            ' "roles": ["OWNER"]}}'
        ),
        '{"long-enough-token-01": {"actor_id": "bad", "name": "x", "roles": ["OWNER"]}}',
        (
            '{"long-enough-token-01": {"actor_id": "00000000-0000-4000-8000-000000000001",'
            ' "name": "x", "roles": ["ADMIN"]}}'
        ),
        '{"long-enough-token-01": "OWNER"}',
    ]:
        with pytest.raises(ValueError):
            StaticTokenIdentityProvider.from_env({"VAANIFLOW_API_TOKENS": raw})


def test_token_map_from_environment_yields_the_configured_principal() -> None:
    configured = StaticTokenIdentityProvider.from_env(
        {
            "VAANIFLOW_API_TOKENS": '{"demo-owner-token-0001": {"actor_id": '
            '"00000000-0000-4000-8000-00000000d001", "name": "demo owner", "roles": ["OWNER"]}}'
        }
    )
    principal = configured.authenticate("demo-owner-token-0001")
    assert principal is not None
    assert principal.principal_id == UUID("00000000-0000-4000-8000-00000000d001")
    assert principal.roles == [Role.OWNER] and principal.authentication_method == "bearer-token"
    assert configured.authenticate("demo-owner-token-0002") is None


# --------------------------------------------------------------------------- #
# Headers and token formats never assert identity or roles
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["admin", "ADMIN", "owner", "OWNER", "operator"])
def test_x_role_cannot_escalate_privileges(role: str) -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    response = client.post(
        f"/runs/{run_id}/approve",
        json={"approval_id": approval_id},
        headers={**auth(REQUESTER), "X-Role": role},
    )
    assert response.status_code == 403
    assert _writes(container) == (0, 0, 0)


@pytest.mark.parametrize("header", ["X-User-Id", "X-Principal-Id"])
def test_identity_headers_cannot_impersonate_another_principal(header: str) -> None:
    container = _fresh()
    run_id, _ = _run_with_approval(owner=REQUESTER)
    victim = str(REQUESTER.principal_id)

    # Alone, the header authenticates nobody.
    alone = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_11}, headers={header: victim}
    )
    assert alone.status_code == 401
    # With another principal's token it changes nothing: still that principal.
    spoofed = client.post(
        f"/runs/{run_id}/process",
        json={"text": KUMAR_11},
        headers={**auth(OTHER_REQUESTER), header: victim},
    )
    assert spoofed.status_code == 403
    approvals = [
        container.repositories.approvals.get_by_id(approval_id=p.approval_id)
        for p in container.repositories.pending_executions.list_by_run(run_id=UUID(run_id))
    ]
    assert len(approvals) == 1  # nothing was superseded


@pytest.mark.parametrize(
    "token",
    [
        "operator:mallory",
        "admin:mallory",
        "owner:mallory",
        str(OWNER.principal_id),
        "00000000-0000-4000-8000-0000000000a1",
    ],
)
def test_identity_asserting_token_formats_do_not_authenticate(token: str) -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    for headers in ({"Authorization": f"Bearer {token}"}, {"Authorization": token}):
        response = client.post(
            f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=headers
        )
        assert response.status_code == 401
    assert _writes(container) == (0, 0, 0)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("approve", {"approved_by": str(uuid4())}),
        ("approve", {"actor_authenticated": True}),
        ("approve", {"actor": {"roles": ["OWNER"]}}),
        ("reject", {"rejected_by": str(uuid4())}),
    ],
)
def test_body_identity_fields_are_refused(path: str, body: dict[str, Any]) -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    response = client.post(
        f"/runs/{run_id}/{path}", json={"approval_id": approval_id, **body}, headers=auth(OWNER)
    )
    assert response.status_code == 422
    assert _writes(container) == (0, 0, 0)


def test_create_run_refuses_a_body_owner() -> None:
    _fresh()
    response = client.post("/runs", json={"owner_id": str(uuid4())}, headers=auth(REQUESTER))
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #


def test_authenticated_owner_approves_and_is_recorded_as_the_approver() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval(owner=REQUESTER)

    response = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OWNER)
    )

    assert response.status_code == 200 and response.json()["status"] == "COMPLETED"
    approval = container.repositories.approvals.get_by_id(approval_id=UUID(approval_id))
    assert approval is not None and approval.status is ApprovalStatus.APPROVED
    assert approval.requested_by == REQUESTER.principal_id
    assert approval.approved_by == OWNER.principal_id
    assert approval.approved_actor == OWNER
    assert approval.actor_authenticated is True
    assert approval.run_id == UUID(run_id)
    assert _writes(container) == (1, 0, 1)


@pytest.mark.parametrize("principal", [REQUESTER, OPERATOR, AUDITOR, NO_ROLES])
def test_authenticated_non_owner_cannot_approve_or_reject(principal: Any) -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval(owner=REQUESTER)
    for path in ("approve", "reject"):
        response = client.post(
            f"/runs/{run_id}/{path}", json={"approval_id": approval_id}, headers=auth(principal)
        )
        assert response.status_code == 403
    approval = container.repositories.approvals.get_by_id(approval_id=UUID(approval_id))
    assert approval is not None and approval.status is ApprovalStatus.REQUESTED
    assert approval.approved_by is None and approval.actor_authenticated is False
    assert _writes(container) == (0, 0, 0)


def test_unauthenticated_approval_is_rejected_and_nothing_executes() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    response = client.post(f"/runs/{run_id}/approve", json={"approval_id": approval_id})
    assert response.status_code == 401
    assert _writes(container) == (0, 0, 0)


def test_orchestrator_refuses_approval_without_a_principal() -> None:
    """Adapters that call the orchestrator directly (e.g. Telegram) cannot bypass it."""
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    with pytest.raises(ApprovalFlowError) as refused:
        container.orchestrator.approve(run_id=UUID(run_id), approval_id=UUID(approval_id))
    assert refused.value.code == "UNAUTHENTICATED"
    with pytest.raises(ApprovalFlowError) as forbidden:
        container.orchestrator.approve(
            run_id=UUID(run_id), approval_id=UUID(approval_id), actor=REQUESTER
        )
    assert forbidden.value.code == "FORBIDDEN"
    assert _writes(container) == (0, 0, 0)


def test_approval_stays_bound_to_its_run() -> None:
    container = _fresh()
    run_a, approval_a = _run_with_approval(owner=REQUESTER)
    run_b, _ = _run_with_approval(owner=REQUESTER, text=KUMAR_11)
    response = client.post(
        f"/runs/{run_b}/approve", json={"approval_id": approval_a}, headers=auth(OWNER)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APPROVAL_RUN_MISMATCH"
    assert _writes(container) == (0, 0, 0)
    assert run_a != run_b


def test_stale_approval_remains_rejected() -> None:
    container = _fresh()
    run_id, first = _run_with_approval(owner=REQUESTER)
    client.post(f"/runs/{run_id}/process", json={"text": KUMAR_11}, headers=auth(REQUESTER))
    superseded = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": first}, headers=auth(OWNER)
    )
    assert superseded.status_code == 409
    assert superseded.json()["detail"]["code"] == "APPROVAL_SUPERSEDED"

    run_2, expiring = _run_with_approval(owner=REQUESTER)
    for inventory in container.repositories.inventory.list_all():
        inventory.reserved_quantity += 1
    expired = client.post(
        f"/runs/{run_2}/approve", json={"approval_id": expiring}, headers=auth(OWNER)
    ).json()
    record = container.repositories.approvals.get_by_id(approval_id=UUID(expiring))
    assert record is not None and record.status is ApprovalStatus.EXPIRED
    assert expired["status"] == "FAILED"
    assert _writes(container) == (0, 0, 0)


def test_repeat_approval_cannot_execute_twice() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval()
    first = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OWNER)
    )
    again = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OWNER)
    )
    assert first.status_code == 200 and again.status_code == 409
    assert _writes(container) == (1, 0, 1)


# --------------------------------------------------------------------------- #
# Run ownership and run state
# --------------------------------------------------------------------------- #


def test_a_user_cannot_process_or_clarify_another_users_run() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval(owner=REQUESTER)
    for path, body in (("process", {"text": KUMAR_11}), ("clarify", {"clarification": KUMAR_11})):
        response = client.post(f"/runs/{run_id}/{path}", json=body, headers=auth(OTHER_REQUESTER))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FORBIDDEN"
    approval = container.repositories.approvals.get_by_id(approval_id=UUID(approval_id))
    assert approval is not None and approval.status is ApprovalStatus.REQUESTED


def test_a_user_cannot_read_another_users_run_but_an_auditor_can() -> None:
    _fresh()
    run_id, _ = _run_with_approval(owner=REQUESTER)
    for suffix in ("", "/trace", "/validation"):
        assert client.get(f"/runs/{run_id}{suffix}", headers=auth(REQUESTER)).status_code == 200
        assert (
            client.get(f"/runs/{run_id}{suffix}", headers=auth(OTHER_REQUESTER)).status_code == 403
        )
        assert client.get(f"/runs/{run_id}{suffix}", headers=auth(AUDITOR)).status_code == 200


def test_audit_requires_read_audit() -> None:
    _fresh()
    run_id, _ = _run_with_approval(owner=REQUESTER)
    assert client.get(f"/runs/{run_id}/audit").status_code == 401
    assert client.get(f"/runs/{run_id}/audit", headers=auth(REQUESTER)).status_code == 403
    for principal in (AUDITOR, OPERATOR, OWNER):
        assert client.get(f"/runs/{run_id}/audit", headers=auth(principal)).status_code == 200


def test_requester_confirms_only_their_own_run() -> None:
    container = _fresh()
    run_id = client.post("/runs", headers=auth(REQUESTER)).json()["run_id"]
    asked = client.post(f"/runs/{run_id}/process", json={"text": LARGE}, headers=auth(REQUESTER))
    assert asked.json()["status"] == "CONFIRMATION_REQUIRED"

    other = client.post(
        f"/runs/{run_id}/confirm", json={"reply": "haan"}, headers=auth(OTHER_REQUESTER)
    )
    assert other.status_code == 403
    pending = container.repositories.pending_confirmations.list_by_run(run_id=UUID(run_id))
    assert pending[0].confirmed_by is None

    own = client.post(f"/runs/{run_id}/confirm", json={"reply": "haan"}, headers=auth(REQUESTER))
    assert own.status_code == 200
    record = container.repositories.pending_confirmations.list_by_run(run_id=UUID(run_id))[0]
    assert record.confirmed_by == REQUESTER.principal_id and record.confirmed_actor == REQUESTER
    assert _writes(container) == (0, 0, 0)  # confirmation never executes


def test_escalation_requires_an_operator_and_supersedes_pending_approval() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval(owner=REQUESTER)
    denied = client.post(f"/runs/{run_id}/handoff", json={"reason": "x"}, headers=auth(REQUESTER))
    assert denied.status_code == 403
    refused_body = client.post(
        f"/runs/{run_id}/handoff",
        json={"reason": "x", "operator_id": str(uuid4())},
        headers=auth(OPERATOR),
    )
    assert refused_body.status_code == 422

    escalated = client.post(
        f"/runs/{run_id}/handoff", json={"reason": "Customer called"}, headers=auth(OPERATOR)
    )
    assert escalated.status_code == 200 and escalated.json()["status"] == "HANDOFF"
    assert escalated.json()["superseded_approval_ids"] == [approval_id]
    case = container.repositories.handoffs.list_by_run(run_id=UUID(run_id))[0]
    assert case.assigned_to == OPERATOR.principal_id

    # The superseded approval can no longer execute, even for the owner.
    late = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OWNER)
    )
    assert late.status_code == 409 and late.json()["detail"]["code"] == "APPROVAL_SUPERSEDED"
    assert _writes(container) == (0, 0, 0)


@pytest.mark.parametrize("principal", [REQUESTER, OPERATOR, STAFF])
def test_escalated_run_cannot_be_reopened(principal: Any) -> None:
    container = _fresh()
    run_id, _ = _run_with_approval(owner=principal if principal is not OPERATOR else REQUESTER)
    client.post(f"/runs/{run_id}/handoff", json={"reason": "x"}, headers=auth(OPERATOR))
    for path, body in (("process", {"text": KUMAR}), ("clarify", {"clarification": KUMAR})):
        response = client.post(f"/runs/{run_id}/{path}", json=body, headers=auth(principal))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "RUN_ESCALATED"
    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.status is VoiceRunStatus.HANDOFF


def test_completed_run_cannot_be_reopened() -> None:
    container = _fresh()
    run_id, approval_id = _run_with_approval(owner=REQUESTER)
    client.post(f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OWNER))
    for path, body in (("process", {"text": KUMAR}), ("clarify", {"clarification": KUMAR})):
        response = client.post(f"/runs/{run_id}/{path}", json=body, headers=auth(REQUESTER))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "RUN_CLOSED"
    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.status is VoiceRunStatus.COMPLETED
    assert _writes(container) == (1, 0, 1)


def test_operator_may_reinstruct_an_open_run_but_never_approve_it() -> None:
    container = _fresh()
    run_id = client.post("/runs", headers=auth(REQUESTER)).json()["run_id"]
    client.post(f"/runs/{run_id}/process", json={"text": AMBIGUOUS}, headers=auth(REQUESTER))
    clarified = client.post(
        f"/runs/{run_id}/clarify", json={"clarification": KUMAR}, headers=auth(OPERATOR)
    )
    assert clarified.status_code == 200
    approval_id = clarified.json()["approval_id"]
    response = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": approval_id}, headers=auth(OPERATOR)
    )
    assert response.status_code == 403
    run = container.repositories.runs.get_by_id(run_id=UUID(run_id))
    assert run is not None and run.owner_id == REQUESTER.principal_id  # ownership unchanged


def test_unknown_resolution_requires_an_operator() -> None:
    _fresh()
    run_id, _ = _run_with_approval()
    body = {"attempt": 1, "outcome": "FAILED", "reason": "x"}
    response = client.post(
        f"/runs/{run_id}/executions/{uuid4()}/resolve", json=body, headers=auth(OWNER)
    )
    assert response.status_code == 403
