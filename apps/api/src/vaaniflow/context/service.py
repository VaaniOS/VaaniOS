from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from vaaniflow.application.ports.business_data import (
    CustomerRepository,
    InventoryRepository,
    ProductRepository,
    QuoteRepository,
    TaxRuleRepository,
)
from vaaniflow.context.models.business_context import (
    BusinessContext,
    ResolvedCustomer,
    ResolvedInventory,
    ResolvedPrice,
    ResolvedProduct,
    ResolvedQuote,
)
from vaaniflow.context.models.resolution import (
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.context.resolvers.customer import CustomerResolver
from vaaniflow.context.resolvers.inventory import InventoryResolver
from vaaniflow.context.resolvers.product import ProductResolver
from vaaniflow.context.resolvers.quote import PriceQuoteResolver
from vaaniflow.context.resolvers.temporal import TemporalResolver
from vaaniflow.domain.models.tax import TaxCalculation
from vaaniflow.domain.schemas.common import DomainSchema
from vaaniflow.domain.schemas.semantic import (
    SemanticState,
    TaxInstruction,
    TaxTreatment,
)


class ContextResolutionOutput(DomainSchema):
    """
    Complete output of the business context resolution pipeline.

    Contains the assembled BusinessContext, all step-by-step ResolutionResults,
    optional TaxCalculation, and a complete point-in-time snapshot of the facts
    retrieved for audit and downstream revalidation.
    """

    business_context: BusinessContext
    resolution_results: list[ResolutionResult]
    tax_calculation: TaxCalculation | None = None
    snapshot: dict[str, Any]

    @property
    def is_fully_resolved(self) -> bool:
        """True if customer, products, and price are resolved with no ambiguities or errors."""
        has_ambiguity = any(r.status == ResolutionStatus.AMBIGUOUS for r in self.resolution_results)
        has_invalid = any(r.status == ResolutionStatus.INVALID for r in self.resolution_results)
        return (
            not has_ambiguity
            and not has_invalid
            and len(self.business_context.resolution_errors) == 0
        )

    @property
    def has_ambiguities(self) -> bool:
        """True if any entity or quote reference had multiple candidates."""
        return any(r.status == ResolutionStatus.AMBIGUOUS for r in self.resolution_results)


class ContextResolutionService:
    """
    Orchestrator for the ACT Context Resolution layer.

    Transforms ungrounded semantic state into grounded business context
    by executing deterministic resolvers against business repositories.
    """

    def __init__(
        self,
        *,
        customer_repo: CustomerRepository,
        product_repo: ProductRepository,
        quote_repo: QuoteRepository,
        inventory_repo: InventoryRepository,
        tax_rule_repo: TaxRuleRepository | None = None,
        timezone_str: str = "Asia/Kolkata",
    ) -> None:
        self._customer_resolver = CustomerResolver(customer_repo)
        self._product_resolver = ProductResolver(product_repo)
        self._temporal_resolver = TemporalResolver(timezone_str)
        self._quote_resolver = PriceQuoteResolver(quote_repo)
        self._inventory_resolver = InventoryResolver(inventory_repo)
        self._tax_rule_repo = tax_rule_repo

    def resolve(
        self,
        *,
        semantic_state: SemanticState,
        run_id: UUID,
        run_timestamp: datetime | None = None,
    ) -> ContextResolutionOutput:
        resolved_at = run_timestamp or datetime.now(UTC)
        context_id = uuid4()

        resolution_results: list[ResolutionResult] = []
        resolution_errors: list[str] = []
        unresolved_references: list[str] = []

        # 1. Resolve Customer
        cust_res, resolved_customer = self._customer_resolver.resolve(
            semantic_customer=semantic_state.customer,
            resolved_at=resolved_at,
        )
        resolution_results.append(cust_res)
        if cust_res.status == ResolutionStatus.AMBIGUOUS:
            resolution_errors.append(f"Ambiguous customer: {cust_res.reason}")
        elif cust_res.status == ResolutionStatus.NOT_FOUND and semantic_state.customer is not None:
            resolution_errors.append(f"Customer not found: {cust_res.reason}")

        # 2. Resolve Products
        resolved_products: list[ResolvedProduct] = []
        for item in semantic_state.items:
            prod_res, resolved_prod = self._product_resolver.resolve(
                semantic_product=item.product,
                resolved_at=resolved_at,
            )
            resolution_results.append(prod_res)
            if resolved_prod is not None:
                resolved_products.append(resolved_prod)
            elif prod_res.status == ResolutionStatus.AMBIGUOUS:
                resolution_errors.append(f"Ambiguous product: {prod_res.reason}")
            else:
                resolution_errors.append(f"Product not found: {prod_res.reason}")

        # 3. Resolve Temporal Expressions (e.g., 'parso')
        resolved_date = None
        for temp_expr in semantic_state.temporal_expressions:
            temp_res, temp_date = self._temporal_resolver.resolve(
                expression=temp_expr,
                run_timestamp=resolved_at,
            )
            resolution_results.append(temp_res)
            if temp_date is not None:
                resolved_date = temp_date

        # 4. Resolve Historical Price / Quote
        primary_product = resolved_products[0] if resolved_products else None
        quote_res, resolved_quote, resolved_price = self._quote_resolver.resolve(
            customer=resolved_customer,
            product=primary_product,
            pricing=semantic_state.pricing,
            references=semantic_state.references,
            resolved_date=resolved_date,
            resolved_at=resolved_at,
        )
        resolution_results.append(quote_res)

        resolved_quotes: list[ResolvedQuote] = []
        if resolved_quote is not None:
            resolved_quotes.append(resolved_quote)

        if quote_res.status == ResolutionStatus.AMBIGUOUS:
            resolution_errors.append(f"Ambiguous quote: {quote_res.reason}")
            unresolved_references.append("HISTORICAL_PRICE")
        elif quote_res.status == ResolutionStatus.INVALID:
            resolution_errors.append(f"Invalid quote: {quote_res.reason}")
            unresolved_references.append("HISTORICAL_PRICE")
        elif quote_res.status == ResolutionStatus.NOT_FOUND and any(
            r.reference_type in {"HISTORICAL_PRICE", "HISTORICAL_QUOTE"}
            for r in semantic_state.references
        ):
            resolution_errors.append(f"Quote not found: {quote_res.reason}")
            unresolved_references.append("HISTORICAL_PRICE")

        # 5. Resolve Inventory
        resolved_inventories: list[ResolvedInventory] = []
        for item, prod in zip(semantic_state.items, resolved_products, strict=False):
            inv_res, inv_records = self._inventory_resolver.resolve(
                product=prod,
                quantity=item.quantity,
                resolved_at=resolved_at,
            )
            resolution_results.append(inv_res)
            resolved_inventories.extend(inv_records)

        # 6. Resolve Tax (if requested in semantic state or default rules)
        tax_calculation = self._calculate_tax(
            semantic_tax=semantic_state.tax,
            resolved_products=resolved_products,
            resolved_price=resolved_price,
            quantity=semantic_state.items[0].quantity if semantic_state.items else None,
            resolved_customer=resolved_customer,
        )

        # 7. Build Snapshot
        snapshot = self._build_snapshot(
            resolved_customer=resolved_customer,
            resolved_products=resolved_products,
            resolved_quotes=resolved_quotes,
            resolved_inventories=resolved_inventories,
            resolved_price=resolved_price,
            tax_calculation=tax_calculation,
            resolved_at=resolved_at,
        )

        business_context = BusinessContext(
            context_id=context_id,
            run_id=run_id,
            customer=resolved_customer,
            products=resolved_products,
            quotes=resolved_quotes,
            inventory=resolved_inventories,
            resolved_price=resolved_price,
            unresolved_references=unresolved_references,
            resolution_errors=resolution_errors,
            resolved_at=resolved_at,
        )

        return ContextResolutionOutput(
            business_context=business_context,
            resolution_results=resolution_results,
            tax_calculation=tax_calculation,
            snapshot=snapshot,
        )

    def _calculate_tax(
        self,
        *,
        semantic_tax: TaxInstruction | None,
        resolved_products: list[ResolvedProduct],
        resolved_price: ResolvedPrice | None,
        quantity: Any,
        resolved_customer: ResolvedCustomer | None,
    ) -> TaxCalculation | None:
        if (
            self._tax_rule_repo is None
            or resolved_price is None
            or not resolved_products
            or quantity is None
        ):
            return None

        product = resolved_products[0].product
        category = product.product_family or product.category or "GENERAL"
        jurisdiction = resolved_customer.customer.state or "KA" if resolved_customer else "KA"
        # Map state to jurisdiction code if needed
        jur_code = (
            "KA" if "karnataka" in jurisdiction.lower() or jurisdiction == "KA" else jurisdiction
        )

        rule = self._tax_rule_repo.get_rule(category=category, jurisdiction=jur_code)
        if rule is None:
            return None

        taxable_amount = resolved_price.unit_price * quantity.value
        treatment = semantic_tax.treatment if semantic_tax else TaxTreatment.EXCLUSIVE

        return rule.calculate(taxable_amount=taxable_amount, treatment=treatment)

    def _build_snapshot(
        self,
        *,
        resolved_customer: ResolvedCustomer | None,
        resolved_products: list[ResolvedProduct],
        resolved_quotes: list[ResolvedQuote],
        resolved_inventories: list[ResolvedInventory],
        resolved_price: ResolvedPrice | None,
        tax_calculation: TaxCalculation | None,
        resolved_at: datetime,
    ) -> dict[str, Any]:
        return {
            "snapshot_timestamp": resolved_at.isoformat(),
            "customer": resolved_customer.model_dump(mode="json") if resolved_customer else None,
            "products": [p.model_dump(mode="json") for p in resolved_products],
            "quotes": [q.model_dump(mode="json") for q in resolved_quotes],
            "inventories": [i.model_dump(mode="json") for i in resolved_inventories],
            "resolved_price": resolved_price.model_dump(mode="json") if resolved_price else None,
            "tax_calculation": tax_calculation.model_dump(mode="json") if tax_calculation else None,
        }
