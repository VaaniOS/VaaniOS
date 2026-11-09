from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from vaaniflow.domain.models.dispatch import Dispatch, DispatchStatus
from vaaniflow.domain.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from vaaniflow.domain.models.order import Order, OrderItem, OrderStatus
from vaaniflow.domain.models.verification import VerificationStatus
from vaaniflow.execution.verifier import VerificationEngine
from vaaniflow.infrastructure.repositories.synthetic_data import (
    CUST_SHARMA_BUILDERS_ID,
    PROD_ULTRATECH_CEMENT_ID,
    WH_PEENYA_ID,
    SyntheticRepositories,
)

_NOW = datetime.now(UTC)


def test_verify_order_success_mismatch_and_missing() -> None:
    repos = SyntheticRepositories()
    verifier = VerificationEngine()
    run_id = uuid4()
    exec_id = uuid4()

    # Seed an order
    order_id = uuid4()
    order = Order(
        order_id=order_id,
        customer_id=CUST_SHARMA_BUILDERS_ID,
        items=[
            OrderItem(
                item_id=uuid4(),
                product_id=PROD_ULTRATECH_CEMENT_ID,
                quantity=200,
                unit="bags",
                unit_price=Decimal(420),
                line_total=Decimal(84000),
            )
        ],
        currency="INR",
        subtotal=Decimal(84000),
        status=OrderStatus.CONFIRMED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.orders.save(order=order)

    # 1. Matching verification
    v_match = verifier.verify_order(
        run_id=run_id,
        execution_id=exec_id,
        order_id=order_id,
        expected_state={
            "status": "CONFIRMED",
            "customer_id": str(CUST_SHARMA_BUILDERS_ID),
            "subtotal": "84000",
            "items_count": 1,
        },
        repositories=repos,
        now=_NOW,
    )
    assert v_match.status == VerificationStatus.VERIFIED
    assert len(v_match.mismatches) == 0
    assert v_match.verified_at == _NOW

    # 2. Mismatch verification (wrong status or subtotal)
    v_mismatch = verifier.verify_order(
        run_id=run_id,
        execution_id=exec_id,
        order_id=order_id,
        expected_state={
            "status": "FULFILLED",  # actual is CONFIRMED
            "subtotal": "90000",  # actual is 84000
        },
        repositories=repos,
        now=_NOW,
    )
    assert v_mismatch.status == VerificationStatus.MISMATCH
    assert len(v_mismatch.mismatches) == 2
    assert v_mismatch.verified_at is None

    # 3. Missing order verification
    missing_id = uuid4()
    v_missing = verifier.verify_order(
        run_id=run_id,
        execution_id=exec_id,
        order_id=missing_id,
        expected_state={"status": "CONFIRMED"},
        repositories=repos,
        now=_NOW,
    )
    assert v_missing.status == VerificationStatus.UNVERIFIED
    assert "could not be read back" in v_missing.mismatches[0]


def test_verify_invoice_success_and_mismatch() -> None:
    repos = SyntheticRepositories()
    verifier = VerificationEngine()
    run_id = uuid4()
    exec_id = uuid4()

    invoice_id = uuid4()
    invoice = Invoice(
        invoice_id=invoice_id,
        order_id=uuid4(),
        customer_id=CUST_SHARMA_BUILDERS_ID,
        items=[
            InvoiceItem(
                item_id=uuid4(),
                product_id=PROD_ULTRATECH_CEMENT_ID,
                quantity=200,
                unit="bags",
                unit_price=Decimal(420),
                line_total=Decimal(84000),
            )
        ],
        currency="INR",
        subtotal=Decimal(84000),
        tax_total=Decimal(23520),
        total=Decimal(107520),
        status=InvoiceStatus.ISSUED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.invoices.save(invoice=invoice)

    # Success
    v_ok = verifier.verify_invoice(
        run_id=run_id,
        execution_id=exec_id,
        invoice_id=invoice_id,
        expected_state={
            "status": "ISSUED",
            "total": "107520",
            "tax_total": "23520",
        },
        repositories=repos,
        now=_NOW,
    )
    assert v_ok.status == VerificationStatus.VERIFIED

    # Mismatch total
    v_bad = verifier.verify_invoice(
        run_id=run_id,
        execution_id=exec_id,
        invoice_id=invoice_id,
        expected_state={"total": "120000"},
        repositories=repos,
        now=_NOW,
    )
    assert v_bad.status == VerificationStatus.MISMATCH


def test_verify_dispatch_and_routing() -> None:
    repos = SyntheticRepositories()
    verifier = VerificationEngine()
    run_id = uuid4()
    exec_id = uuid4()

    dispatch_id = uuid4()
    dispatch = Dispatch(
        dispatch_id=dispatch_id,
        order_id=uuid4(),
        customer_id=CUST_SHARMA_BUILDERS_ID,
        warehouse_id=WH_PEENYA_ID,
        status=DispatchStatus.DISPATCHED,
        recipient_name="Sharma Site Mgr",
        delivery_address="Site 12",
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.dispatches.save(dispatch=dispatch)

    # Router call for dispatch
    v_disp = verifier.verify(
        run_id=run_id,
        execution_id=exec_id,
        entity_type="dispatch",
        entity_id=dispatch_id,
        expected_state={
            "status": "DISPATCHED",
            "warehouse_id": str(WH_PEENYA_ID),
        },
        repositories=repos,
        now=_NOW,
    )
    assert v_disp.status == VerificationStatus.VERIFIED

    # Unknown entity router call
    v_unknown = verifier.verify(
        run_id=run_id,
        execution_id=exec_id,
        entity_type="unknown_widget",
        entity_id=uuid4(),
        expected_state={},
        repositories=repos,
        now=_NOW,
    )
    assert v_unknown.status == VerificationStatus.UNVERIFIED
    assert "Unknown entity type" in v_unknown.mismatches[0]
