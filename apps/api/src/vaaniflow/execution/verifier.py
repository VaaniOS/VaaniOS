from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.domain.models.verification import (
    Verification,
    VerificationStatus,
)
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories


class VerificationEngine:
    """
    Independent read-back verification engine.

    Enforces that tool-claimed business outcomes must be explicitly verified
    by reading back canonical records and comparing expected vs actual state.
    """

    VERSION = "1.0"

    def verify_order(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        order_id: UUID,
        expected_state: dict[str, Any],
        repositories: SyntheticRepositories,
        now: datetime,
    ) -> Verification:
        order = repositories.orders.get_by_id(order_id=order_id)
        if order is None:
            verification = Verification(
                verification_id=uuid4(),
                run_id=run_id,
                execution_id=execution_id,
                status=VerificationStatus.UNVERIFIED,
                expected_state=expected_state,
                actual_state={},
                mismatches=[f"Order {order_id} could not be read back from repository."],
                verifier_version=self.VERSION,
            )
            repositories.verifications.save(verification=verification)
            return verification

        actual_state: dict[str, Any] = {
            "order_id": str(order.order_id),
            "customer_id": str(order.customer_id),
            "recipient_name": order.recipient_name,
            "delivery_address": order.delivery_address,
            "subtotal": str(order.subtotal),
            "currency": order.currency,
            "items_count": len(order.items),
            "status": order.status.value,
        }

        mismatches = self._compare_states(expected_state, actual_state)
        status = VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED

        verification = Verification(
            verification_id=uuid4(),
            run_id=run_id,
            execution_id=execution_id,
            status=status,
            expected_state=expected_state,
            actual_state=actual_state,
            mismatches=mismatches,
            verified_at=now if status == VerificationStatus.VERIFIED else None,
            verifier_version=self.VERSION,
        )
        repositories.verifications.save(verification=verification)
        return verification

    def verify_invoice(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        invoice_id: UUID,
        expected_state: dict[str, Any],
        repositories: SyntheticRepositories,
        now: datetime,
    ) -> Verification:
        invoice = repositories.invoices.get_by_id(invoice_id=invoice_id)
        if invoice is None:
            verification = Verification(
                verification_id=uuid4(),
                run_id=run_id,
                execution_id=execution_id,
                status=VerificationStatus.UNVERIFIED,
                expected_state=expected_state,
                actual_state={},
                mismatches=[f"Invoice {invoice_id} could not be read back from repository."],
                verifier_version=self.VERSION,
            )
            repositories.verifications.save(verification=verification)
            return verification

        actual_state: dict[str, Any] = {
            "invoice_id": str(invoice.invoice_id),
            "order_id": str(invoice.order_id),
            "customer_id": str(invoice.customer_id),
            "subtotal": str(invoice.subtotal),
            "tax_total": str(invoice.tax_total),
            "total": str(invoice.total),
            "currency": invoice.currency,
            "items_count": len(invoice.items),
            "status": invoice.status.value,
        }

        mismatches = self._compare_states(expected_state, actual_state)
        status = VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED

        verification = Verification(
            verification_id=uuid4(),
            run_id=run_id,
            execution_id=execution_id,
            status=status,
            expected_state=expected_state,
            actual_state=actual_state,
            mismatches=mismatches,
            verified_at=now if status == VerificationStatus.VERIFIED else None,
            verifier_version=self.VERSION,
        )
        repositories.verifications.save(verification=verification)
        return verification

    def verify_dispatch(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        dispatch_id: UUID,
        expected_state: dict[str, Any],
        repositories: SyntheticRepositories,
        now: datetime,
    ) -> Verification:
        dispatch = repositories.dispatches.get_by_id(dispatch_id=dispatch_id)
        if dispatch is None:
            verification = Verification(
                verification_id=uuid4(),
                run_id=run_id,
                execution_id=execution_id,
                status=VerificationStatus.UNVERIFIED,
                expected_state=expected_state,
                actual_state={},
                mismatches=[f"Dispatch {dispatch_id} could not be read back from repository."],
                verifier_version=self.VERSION,
            )
            repositories.verifications.save(verification=verification)
            return verification

        actual_state: dict[str, Any] = {
            "dispatch_id": str(dispatch.dispatch_id),
            "order_id": str(dispatch.order_id),
            "customer_id": str(dispatch.customer_id),
            "warehouse_id": str(dispatch.warehouse_id),
            "status": dispatch.status.value,
            "recipient_name": dispatch.recipient_name,
            "delivery_address": dispatch.delivery_address,
        }

        mismatches = self._compare_states(expected_state, actual_state)
        status = VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED

        verification = Verification(
            verification_id=uuid4(),
            run_id=run_id,
            execution_id=execution_id,
            status=status,
            expected_state=expected_state,
            actual_state=actual_state,
            mismatches=mismatches,
            verified_at=now if status == VerificationStatus.VERIFIED else None,
            verifier_version=self.VERSION,
        )
        repositories.verifications.save(verification=verification)
        return verification

    def verify(
        self,
        *,
        run_id: UUID,
        execution_id: UUID,
        entity_type: str,
        entity_id: UUID,
        expected_state: dict[str, Any],
        repositories: SyntheticRepositories,
        now: datetime,
    ) -> Verification:
        """Route verification to the appropriate entity verifier."""
        entity_key = entity_type.strip().lower()
        if entity_key == "order":
            return self.verify_order(
                run_id=run_id,
                execution_id=execution_id,
                order_id=entity_id,
                expected_state=expected_state,
                repositories=repositories,
                now=now,
            )
        elif entity_key == "invoice":
            return self.verify_invoice(
                run_id=run_id,
                execution_id=execution_id,
                invoice_id=entity_id,
                expected_state=expected_state,
                repositories=repositories,
                now=now,
            )
        elif entity_key == "dispatch":
            return self.verify_dispatch(
                run_id=run_id,
                execution_id=execution_id,
                dispatch_id=entity_id,
                expected_state=expected_state,
                repositories=repositories,
                now=now,
            )
        else:
            verification = Verification(
                verification_id=uuid4(),
                run_id=run_id,
                execution_id=execution_id,
                status=VerificationStatus.UNVERIFIED,
                expected_state=expected_state,
                actual_state={},
                mismatches=[f"Unknown entity type '{entity_type}' for verification."],
                verifier_version=self.VERSION,
            )
            repositories.verifications.save(verification=verification)
            return verification

    def _compare_states(self, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
        mismatches: list[str] = []
        for key, exp_val in expected.items():
            if key not in actual:
                mismatches.append(f"Missing expected field '{key}' in actual read-back.")
                continue

            act_val = actual[key]
            if not self._values_match(exp_val, act_val):
                mismatches.append(
                    f"Field '{key}' mismatch: expected {exp_val!r}, found {act_val!r}."
                )
        return mismatches

    def _values_match(self, v1: Any, v2: Any) -> bool:
        if v1 == v2:
            return True
        # Allow string to decimal / int equivalence
        try:
            d1 = Decimal(str(v1))
            d2 = Decimal(str(v2))
            if d1 == d2:
                return True
        except (ValueError, TypeError, DecimalException):
            return (
                v1.strip().upper() == v2.strip().upper()
                if isinstance(v1, str) and isinstance(v2, str)
                else False
            )

        # String case-insensitive comparison for enum-like values
        if isinstance(v1, str) and isinstance(v2, str):
            return v1.strip().upper() == v2.strip().upper()

        return False
