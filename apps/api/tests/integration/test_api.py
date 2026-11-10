from fastapi.testclient import TestClient

from tests.auth_support import auth, provider
from vaaniflow.api.app import app
from vaaniflow.api.dependencies import reset_container
from vaaniflow.infrastructure.repositories.synthetic_data import SYNTHETIC_BUSINESS_TIME

client = TestClient(app)


def setup_function() -> None:
    # Quotes are only valid relative to the dataset's business clock.
    reset_container(clock=lambda: SYNTHETIC_BUSINESS_TIME, identity_provider=provider())


def test_health_endpoint() -> None:
    res = client.get("/health", headers=auth())
    assert res.status_code == 200
    assert res.json() == {"status": "healthy", "service": "vaaniflow"}


def test_create_and_get_run() -> None:
    res = client.post(
        "/runs", json={"text": "Send 200 bags of cement to Sharma Builders."}, headers=auth()
    )
    assert res.status_code == 201
    data = res.json()
    assert "run_id" in data
    run_id = data["run_id"]

    # Get run details
    get_res = client.get(f"/runs/{run_id}", headers=auth())
    assert get_res.status_code == 200
    assert get_res.json()["run_id"] == run_id


def test_process_run_and_trace() -> None:
    # 1. Create run
    create_res = client.post("/runs", headers=auth())
    run_id = create_res.json()["run_id"]

    # 2. Process run
    proc_res = client.post(
        f"/runs/{run_id}/process",
        json={
            "text": "Send 200 bags of UltraTech cement to Sharma Builders at the rate quoted day before yesterday and dispatch.",
        },
        headers=auth(),
    )
    assert proc_res.status_code == 200
    proc_data = proc_res.json()
    assert proc_data["decision"] == "APPROVAL_REQUIRED"

    # 3. Get trace
    trace_res = client.get(f"/runs/{run_id}/trace", headers=auth())
    assert trace_res.status_code == 200
    trace_data = trace_res.json()
    assert len(trace_data["events"]) > 0

    # 4. Approve the approval the system requested
    approve_res = client.post(
        f"/runs/{run_id}/approve", json={"approval_id": proc_data["approval_id"]}, headers=auth()
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "COMPLETED"
    assert approve_res.json()["executed_tools"] == ["create_order", "dispatch_order"]


def test_search_endpoints() -> None:
    # Customers
    cust_res = client.get("/customers/search?query=Sharma", headers=auth())
    assert cust_res.status_code == 200
    assert len(cust_res.json()) >= 2

    # Products
    prod_res = client.get("/products/search?query=UltraTech", headers=auth())
    assert prod_res.status_code == 200
    assert len(prod_res.json()) >= 1

    # Quotes
    quotes_res = client.get("/quotes/search", headers=auth())
    assert quotes_res.status_code == 200
    assert len(quotes_res.json()) >= 1

    # Inventory
    inv_res = client.get("/inventory/search", headers=auth())
    assert inv_res.status_code == 200
    assert len(inv_res.json()) >= 1


def test_sandbox_endpoints() -> None:
    # List scenarios
    scenarios_res = client.get("/sandbox/scenarios", headers=auth())
    assert scenarios_res.status_code == 200
    scenarios = scenarios_res.json()
    assert len(scenarios) == 10

    # Run single scenario
    run_sc_res = client.post("/sandbox/scenarios/scenario_a_happy_path/run", headers=auth())
    assert run_sc_res.status_code == 200
    assert run_sc_res.json()["passed"] is True

    # Evaluate all
    eval_all_res = client.post("/sandbox/evaluate-all", headers=auth())
    assert eval_all_res.status_code == 200
    suite = eval_all_res.json()
    assert suite["total_scenarios"] == 10
    assert suite["passed_scenarios"] == 10
    assert suite["safety_violations"] == 0
