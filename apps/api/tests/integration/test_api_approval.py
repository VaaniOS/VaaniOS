"""Phase A P0 regressions at API level: approval is bound to the stored plan."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from vaaniflow.api.app import app
from vaaniflow.api.dependencies import AppContainer, reset_container
from vaaniflow.infrastructure.repositories.synthetic_data import SYNTHETIC_BUSINESS_TIME

client = TestClient(app)

KUMAR_DISPATCH = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."


def _fresh() -> AppContainer:
    return reset_container(clock=lambda: SYNTHETIC_BUSINESS_TIME)


def _process(text: str) -> tuple[str, dict]:  # type: ignore[type-arg]
    run_id = client.post("/runs").json()["run_id"]
    response = client.post(f"/runs/{run_id}/process", json={"text": text})
    assert response.status_code == 200
    return run_id, response.json()


def _writes(container: AppContainer) -> tuple[int, int, int]:
    repos = container.repositories
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


def test_approve_executes_the_stored_plan_not_a_hard_coded_order() -> None:
    container = _fresh()
    run_id, processed = _process(KUMAR_DISPATCH)
    assert processed["status"] == "APPROVAL_REQUIRED"
    assert processed["planned_tools"] == ["create_order", "dispatch_order"]

    response = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": processed["approval_id"]}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    order = container.repositories.orders.list_all()[0]
    customer = container.repositories.customers.get_by_id(customer_id=order.customer_id)
    product = container.repositories.products.get_by_id(product_id=order.items[0].product_id)
    assert customer is not None and customer.name == "Kumar Constructions"
    assert product is not None and product.sku == "CEM-ACC-001"
    assert order.items[0].quantity == 10
    assert _writes(container) == (1, 0, 1)


def test_approve_requires_an_approval_id() -> None:
    container = _fresh()
    run_id, _ = _process(KUMAR_DISPATCH)

    response = client.post(f"/runs/{run_id}/approve", json={})

    assert response.status_code == 422
    assert _writes(container) == (0, 0, 0)


def test_approval_of_another_run_is_refused() -> None:
    container = _fresh()
    _, run_a = _process(KUMAR_DISPATCH)
    run_b_id, _ = _process(KUMAR_DISPATCH)

    response = client.post(f"/runs/{run_b_id}/approve", json={"approval_id": run_a["approval_id"]})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "APPROVAL_RUN_MISMATCH"
    assert _writes(container) == (0, 0, 0)


def test_unknown_approval_id_is_refused() -> None:
    container = _fresh()
    run_id, _ = _process(KUMAR_DISPATCH)

    response = client.post(f"/runs/{run_id}/approve", json={"approval_id": str(uuid4())})

    assert response.status_code == 404
    assert _writes(container) == (0, 0, 0)


def test_rejected_approval_cannot_be_approved_later() -> None:
    container = _fresh()
    run_id, processed = _process(KUMAR_DISPATCH)

    rejected = client.post(f"/runs/{run_id}/reject", json={"approval_id": processed["approval_id"]})
    approved = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": processed["approval_id"]}
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "BLOCKED"
    assert approved.status_code == 409
    assert approved.json()["detail"]["code"] == "APPROVAL_NOT_PENDING"
    assert _writes(container) == (0, 0, 0)


def test_client_cannot_self_approve_through_process() -> None:
    container = _fresh()
    run_id = client.post("/runs").json()["run_id"]

    response = client.post(
        f"/runs/{run_id}/process", json={"text": KUMAR_DISPATCH, "is_approved": True}
    )

    assert response.status_code == 422
    assert _writes(container) == (0, 0, 0)


def test_client_cannot_inject_faults_through_process() -> None:
    container = _fresh()
    run_id = client.post("/runs").json()["run_id"]

    response = client.post(
        f"/runs/{run_id}/process",
        json={"text": KUMAR_DISPATCH, "faults": {"override_approval_snapshot": "x"}},
    )

    assert response.status_code == 422
    assert _writes(container) == (0, 0, 0)


def test_negated_dispatch_is_not_approvable_over_http() -> None:
    container = _fresh()
    _, processed = _process(
        "Sharma Builders ko 20 bags UltraTech cement ₹400 per bag pe dispatch mat karo."
    )

    assert processed["status"] == "CLARIFICATION_REQUIRED"
    assert processed["approval_id"] is None
    assert processed["actionability"] == "CLARIFICATION_REQUIRED"
    assert "NEGATED_ACTION" in [r["code"] for r in processed["evaluation_reasons"]]
    assert _writes(container) == (0, 0, 0)


def test_clarification_response_exposes_reasons_and_ambiguities() -> None:
    _fresh()
    _, processed = _process("Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo.")

    assert processed["decision"] == "CLARIFY"
    assert [a["candidates"] for a in processed["ambiguities"]] == [
        ["UltraTech cement", "ACC cement"]
    ]
    assert "SEMANTIC_AMBIGUITY" in [r["code"] for r in processed["evaluation_reasons"]]
