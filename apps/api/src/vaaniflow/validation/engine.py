from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.context.resolvers.quote import HISTORICAL_REFERENCE_TYPES
from vaaniflow.domain.models.customer import CustomerStatus
from vaaniflow.domain.models.product import ProductStatus
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.models.tax import TaxCalculation
from vaaniflow.domain.models.validation import (
    ValidationCheck,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)
from vaaniflow.domain.schemas.semantic import (
    SemanticState,
)

DISCRETE_UNITS = {"bag", "bags", "piece", "pieces", "box", "boxes", "bundle", "bundles"}
SUSPICIOUS_MAGNITUDE_THRESHOLD = Decimal(1000)


class ValidationEngine:
    """
    Deterministic business validation engine.

    Answers: 'Is this proposed state valid given actual business state?'
    Enforces business rules deterministically without LLM assumptions.
    """

    VERSION = "1.0"

    def validate(
        self,
        *,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        tax_calculation: TaxCalculation | None = None,
        run_id: UUID,
        validated_at: datetime | None = None,
    ) -> ValidationResult:
        now = validated_at or datetime.now(UTC)
        checks: list[ValidationCheck] = []

        # 1. Customer Identity Check
        self._validate_customer(business_context, checks)

        # 2. Product Identity Check
        self._validate_products(business_context, checks)

        # 3. Quantity and Units
        self._validate_quantities(semantic_state, business_context, checks)

        # 4. Inventory Availability
        self._validate_inventory(semantic_state, business_context, checks)

        # 5. Pricing, Quotes, and Tax
        self._validate_pricing(semantic_state, business_context, tax_calculation, checks)

        # 6. Resolution Cleanliness & Safety Invariants
        self._validate_safety_invariants(semantic_state, business_context, checks)

        # Aggregate overall validation status
        overall_status = ValidationStatus.PASSED
        if any(c.status == ValidationStatus.FAILED for c in checks):
            overall_status = ValidationStatus.FAILED
        elif any(c.status == ValidationStatus.WARNING for c in checks):
            overall_status = ValidationStatus.WARNING

        return ValidationResult(
            validation_id=uuid4(),
            run_id=run_id,
            status=overall_status,
            checks=checks,
            validated_at=now,
            validator_version=self.VERSION,
        )

    def _validate_customer(
        self,
        business_context: BusinessContext,
        checks: list[ValidationCheck],
    ) -> None:
        if business_context.customer is None:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="CUSTOMER_IDENTITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.CRITICAL,
                    message="Customer identity is missing or unresolved.",
                    field="customer",
                    expected="Resolved active customer",
                    actual=None,
                )
            )
            return

        cust = business_context.customer.customer
        if cust.status != CustomerStatus.ACTIVE:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="CUSTOMER_IDENTITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.CRITICAL,
                    message=f"Customer '{cust.name}' is {cust.status.value}.",
                    field="customer.status",
                    expected=CustomerStatus.ACTIVE.value,
                    actual=cust.status.value,
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="CUSTOMER_IDENTITY",
                    status=ValidationStatus.PASSED,
                    severity=ValidationSeverity.INFO,
                    message=f"Customer '{cust.name}' ({cust.customer_id}) is resolved and active.",
                    field="customer",
                    expected=CustomerStatus.ACTIVE.value,
                    actual=CustomerStatus.ACTIVE.value,
                    evidence=[f"Tax ID: {cust.tax_id or 'N/A'}", f"City: {cust.city or 'N/A'}"],
                )
            )

    def _validate_products(
        self,
        business_context: BusinessContext,
        checks: list[ValidationCheck],
    ) -> None:
        if not business_context.products:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="PRODUCT_IDENTITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.CRITICAL,
                    message="No catalog product resolved for requested items.",
                    field="products",
                    expected="At least one resolved product",
                    actual="0 products",
                )
            )
            return

        for p in business_context.products:
            prod = p.product
            if prod.status != ProductStatus.ACTIVE:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="PRODUCT_IDENTITY",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Product '{prod.name}' ({prod.sku}) is {prod.status.value}.",
                        field=f"product.{prod.sku}.status",
                        expected=ProductStatus.ACTIVE.value,
                        actual=prod.status.value,
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="PRODUCT_IDENTITY",
                        status=ValidationStatus.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Product '{prod.name}' ({prod.sku}) is resolved and active.",
                        field=f"product.{prod.sku}",
                        expected=ProductStatus.ACTIVE.value,
                        actual=ProductStatus.ACTIVE.value,
                    )
                )

    def _validate_quantities(
        self,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        checks: list[ValidationCheck],
    ) -> None:
        for idx, item in enumerate(semantic_state.items):
            qty = item.quantity
            if qty is None:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUANTITY_PRESENT",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.HIGH,
                        message=f"Item {idx + 1} has no specified quantity.",
                        field=f"items[{idx}].quantity",
                    )
                )
                continue

            if qty.value <= 0:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUANTITY_POSITIVE",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Item {idx + 1} quantity must be strictly positive, got {qty.value}.",
                        field=f"items[{idx}].quantity",
                        expected="> 0",
                        actual=str(qty.value),
                    )
                )

            # Check discrete unit integer requirement
            unit_norm = (qty.unit or "").lower()
            if unit_norm in DISCRETE_UNITS and qty.value % Decimal(1) != Decimal(0):
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUANTITY_INTEGER",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.HIGH,
                        message=f"Item {idx + 1} with unit '{qty.unit}' cannot have a fractional quantity ({qty.value}).",
                        field=f"items[{idx}].quantity",
                        expected="Integer",
                        actual=str(qty.value),
                    )
                )

            # Scenario B: Suspicious magnitude check (e.g., 200 vs 2000 ASR confusion)
            if qty.value >= SUSPICIOUS_MAGNITUDE_THRESHOLD:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUANTITY_MAGNITUDE",
                        status=ValidationStatus.WARNING,
                        severity=ValidationSeverity.HIGH,
                        message=f"Order quantity {qty.value} {qty.unit or 'units'} is unusually large (>= {SUSPICIOUS_MAGNITUDE_THRESHOLD}). Explicit confirmation required.",
                        field=f"items[{idx}].quantity",
                        expected=f"< {SUSPICIOUS_MAGNITUDE_THRESHOLD}",
                        actual=str(qty.value),
                        evidence=[
                            "Potential speech-to-text magnitude mishearing (e.g., 200 -> 2000)"
                        ],
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUANTITY_MAGNITUDE",
                        status=ValidationStatus.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Quantity {qty.value} {qty.unit or 'units'} is within plausible magnitude.",
                        field=f"items[{idx}].quantity",
                        actual=str(qty.value),
                    )
                )

            # Unit compatibility with resolved product
            if idx < len(business_context.products):
                prod = business_context.products[idx].product
                prod_unit = prod.unit.lower()
                if (
                    unit_norm
                    and unit_norm != prod_unit
                    and not (unit_norm == "bags" and prod_unit == "bag")
                ):
                    checks.append(
                        ValidationCheck(
                            check_id=uuid4(),
                            check_type="UNIT_COMPATIBILITY",
                            status=ValidationStatus.FAILED,
                            severity=ValidationSeverity.CRITICAL,
                            message=f"Requested unit '{qty.unit}' does not match product catalog unit '{prod.unit}'.",
                            field=f"items[{idx}].unit",
                            expected=prod.unit,
                            actual=qty.unit,
                        )
                    )
                else:
                    checks.append(
                        ValidationCheck(
                            check_id=uuid4(),
                            check_type="UNIT_COMPATIBILITY",
                            status=ValidationStatus.PASSED,
                            severity=ValidationSeverity.INFO,
                            message=f"Unit '{qty.unit or prod.unit}' matches product catalog unit '{prod.unit}'.",
                            field=f"items[{idx}].unit",
                            expected=prod.unit,
                            actual=qty.unit or prod.unit,
                        )
                    )

    def _validate_inventory(
        self,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        checks: list[ValidationCheck],
    ) -> None:
        if not business_context.inventory:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="INVENTORY_AVAILABILITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.HIGH,
                    message="No inventory records available for validation.",
                    field="inventory",
                )
            )
            return

        for idx, prod in enumerate(business_context.products):
            matching_inv = [
                i
                for i in business_context.inventory
                if i.inventory.product_id == prod.product.product_id
            ]
            if not matching_inv:
                continue

            total_available = sum(i.inventory.available_quantity for i in matching_inv)
            total_reserved = sum(i.inventory.reserved_quantity for i in matching_inv)
            net_stock = total_available - total_reserved

            qty = semantic_state.items[idx].quantity if idx < len(semantic_state.items) else None
            req_qty = int(qty.value) if qty else 0

            # Scenario E: Inventory shortage check
            if req_qty > net_stock:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="INVENTORY_AVAILABILITY",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.HIGH,
                        message=f"Inventory shortage for {prod.product.sku}: requested {req_qty} units, but net available stock is {net_stock}.",
                        field=f"inventory.{prod.product.sku}",
                        expected=f">= {req_qty}",
                        actual=str(net_stock),
                        evidence=[f"Available: {total_available}, Reserved: {total_reserved}"],
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="INVENTORY_AVAILABILITY",
                        status=ValidationStatus.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Stock sufficient for {prod.product.sku}: requested {req_qty}, net available {net_stock}.",
                        field=f"inventory.{prod.product.sku}",
                        expected=f">= {req_qty}",
                        actual=str(net_stock),
                        evidence=[f"Available: {total_available}, Reserved: {total_reserved}"],
                    )
                )

    def _validate_pricing(
        self,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        tax_calculation: TaxCalculation | None,
        checks: list[ValidationCheck],
    ) -> None:
        business_date = business_context.business_date or business_context.resolved_at.date()

        # Scenario D: Expired quote check. A VALID status is not enough: the
        # business date must also lie inside the quote's validity window.
        for q in business_context.quotes:
            quote = q.quote
            if quote.status != QuoteStatus.VALID:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUOTE_VALIDITY",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Historical quote {quote.quote_id} is {quote.status.value} (valid until {quote.valid_until}).",
                        field=f"quote.{quote.quote_id}.status",
                        expected=QuoteStatus.VALID.value,
                        actual=quote.status.value,
                        evidence=_quote_evidence(quote),
                    )
                )
            elif not quote.is_applicable_on(business_date):
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUOTE_VALIDITY",
                        status=ValidationStatus.FAILED,
                        severity=ValidationSeverity.CRITICAL,
                        message=(
                            f"Quote {quote.quote_id} (quoted {quote.quoted_on}, valid until "
                            f"{quote.valid_until}) is not applicable on {business_date}."
                        ),
                        field=f"quote.{quote.quote_id}.valid_until",
                        expected=f"{quote.quoted_on} <= {business_date} <= valid_until",
                        actual=str(quote.valid_until),
                        evidence=_quote_evidence(quote),
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="QUOTE_VALIDITY",
                        status=ValidationStatus.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Quote {quote.quote_id} is valid and active.",
                        field=f"quote.{quote.quote_id}.status",
                        expected=QuoteStatus.VALID.value,
                        actual=QuoteStatus.VALID.value,
                    )
                )

        has_historical_ref = any(
            r.reference_type in HISTORICAL_REFERENCE_TYPES for r in semantic_state.references
        )
        if (
            has_historical_ref
            and not business_context.quotes
            and "HISTORICAL_PRICE" in business_context.unresolved_references
        ):
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="QUOTE_REFERENCE",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.HIGH,
                    message="The referenced rate could not be matched to a business quote: "
                    + "; ".join(
                        e
                        for e in business_context.resolution_errors
                        if e.startswith(("Quote not found", "Ambiguous quote", "Invalid quote"))
                    ),
                    field="references.HISTORICAL_PRICE",
                )
            )

        spoken_amounts = [p.amount for p in semantic_state.pricing if p.amount is not None]
        if business_context.resolved_price is None and spoken_amounts and not has_historical_ref:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="PRICE_AUTHORITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.HIGH,
                    message=(
                        f"Spoken price {spoken_amounts[0]} is not backed by any business quote "
                        f"valid on {business_date}; a spoken price is not authoritative."
                    ),
                    field="pricing.amount",
                    actual=str(spoken_amounts[0]),
                )
            )

        if business_context.resolved_price is None:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="PRICE_RESOLVED",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.CRITICAL,
                    message="No valid unit price could be resolved from quotes or records.",
                    field="resolved_price",
                )
            )
            return

        price = business_context.resolved_price
        if price.source_quote_id is None:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="PRICE_AUTHORITY",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.CRITICAL,
                    message="The resolved unit price has no business quote as its source.",
                    field="resolved_price.source_quote_id",
                )
            )
        checks.append(
            ValidationCheck(
                check_id=uuid4(),
                check_type="PRICE_RESOLVED",
                status=ValidationStatus.PASSED,
                severity=ValidationSeverity.INFO,
                message=f"Unit price established at {price.unit_price} {price.currency}/{price.unit}.",
                field="resolved_price",
                actual=f"{price.unit_price} {price.currency}",
                evidence=[f"Quote source: {price.source_quote_id or 'Direct spoken'}"],
            )
        )

        # Spoken price vs quote price consistency
        if semantic_state.pricing and price.source_quote_id is not None:
            spoken_amount = semantic_state.pricing[0].amount
            if spoken_amount is not None and spoken_amount != price.unit_price:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="PRICE_CONSISTENCY",
                        status=ValidationStatus.WARNING,
                        severity=ValidationSeverity.HIGH,
                        message=f"Spoken price claim ({spoken_amount}) differs from business quote price ({price.unit_price}).",
                        field="pricing.amount",
                        expected=str(price.unit_price),
                        actual=str(spoken_amount),
                    )
                )

        # Tax check
        if semantic_state.tax is not None:
            if tax_calculation is None:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="TAX_CALCULATION",
                        status=ValidationStatus.WARNING,
                        severity=ValidationSeverity.WARNING,
                        message="Tax was requested in speech but could not be calculated by rules layer.",
                        field="tax",
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        check_id=uuid4(),
                        check_type="TAX_CALCULATION",
                        status=ValidationStatus.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Tax calculated successfully: {tax_calculation.total_tax} (Rule: {tax_calculation.rule_version}).",
                        field="tax",
                        evidence=[f"Provenance: {tax_calculation.provenance}"],
                    )
                )

    def _validate_safety_invariants(
        self,
        semantic_state: SemanticState,
        business_context: BusinessContext,
        checks: list[ValidationCheck],
    ) -> None:
        if business_context.resolution_errors:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="RESOLUTION_CLEANLINESS",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.HIGH,
                    message=f"Unresolved errors in business context: {'; '.join(business_context.resolution_errors)}",
                    field="context.resolution_errors",
                )
            )

        if business_context.unresolved_references:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="UNRESOLVED_REFERENCES",
                    status=ValidationStatus.FAILED,
                    severity=ValidationSeverity.HIGH,
                    message=f"Unresolved references remaining: {', '.join(business_context.unresolved_references)}",
                    field="context.unresolved_references",
                )
            )

        if semantic_state.negated_actions:
            checks.append(
                ValidationCheck(
                    check_id=uuid4(),
                    check_type="NEGATED_ACTIONS",
                    status=ValidationStatus.WARNING,
                    severity=ValidationSeverity.HIGH,
                    message=f"User explicitly instructed NOT to execute: {', '.join(a.action_type.value for a in semantic_state.negated_actions)}.",
                    field="negated_actions",
                )
            )


def _quote_evidence(quote: Quote) -> list[str]:
    """Which quote record was rejected, so a handoff keeps the user's reference."""
    return [
        (
            f"Quote {quote.quote_id}: {quote.unit_price} {quote.currency}/{quote.unit}, "
            f"quoted {quote.quoted_on}, valid until {quote.valid_until}, "
            f"status {quote.status.value}"
        )
    ]
