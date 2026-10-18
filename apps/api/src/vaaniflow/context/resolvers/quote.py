from datetime import date, datetime
from uuid import uuid4

from vaaniflow.application.ports.business_data import QuoteRepository
from vaaniflow.context.models.business_context import (
    ResolvedCustomer,
    ResolvedPrice,
    ResolvedProduct,
    ResolvedQuote,
)
from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.models.quote import Quote, QuoteStatus
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    PriceSource,
    ReferenceType,
    SemanticPrice,
    SemanticReference,
)


class PriceQuoteResolver:
    """
    Deterministic historical quote and price resolver.

    Resolves historical quote references (e.g., 'Rate wahi jo parso bataya tha')
    against business quote records. Compares spoken price claims against
    authoritative business quotes and prevents applying expired or mismatched quotes.
    """

    def __init__(self, quote_repo: QuoteRepository) -> None:
        self._quote_repo = quote_repo

    def resolve(
        self,
        *,
        customer: ResolvedCustomer | None,
        product: ResolvedProduct | None,
        pricing: list[SemanticPrice],
        references: list[SemanticReference],
        resolved_date: date | None,
        resolved_at: datetime,
    ) -> tuple[ResolutionResult, ResolvedQuote | None, ResolvedPrice | None]:
        resolution_id = uuid4()
        primary_price = pricing[0] if pricing else None

        # Check if a historical price/quote reference exists
        has_historical_ref = any(
            ref.reference_type in {ReferenceType.HISTORICAL_PRICE, ReferenceType.HISTORICAL_QUOTE}
            for ref in references
        ) or (
            primary_price is not None
            and primary_price.source
            in {
                PriceSource.HISTORICAL_REFERENCE,
                PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE,
            }
        )

        query = primary_price.surface_text if primary_price else "historical_rate"

        # If there is no historical reference and pricing is purely spoken
        if not has_historical_ref:
            if (
                primary_price is not None
                and primary_price.amount is not None
                and product is not None
                and customer is not None
            ):
                resolved_price = ResolvedPrice(
                    product_id=product.product.product_id,
                    customer_id=customer.customer.customer_id,
                    unit=primary_price.per_unit or product.product.unit,
                    unit_price=primary_price.amount,
                    currency=primary_price.currency or "INR",
                    source_quote_id=None,
                    resolved_on=resolved_date or resolved_at.date(),
                )
                candidate = ResolutionCandidate(
                    candidate_id=uuid4(),
                    entity_id=uuid4(),
                    display_name=f"Direct spoken price {primary_price.amount} {primary_price.currency or 'INR'}",
                    confidence=Confidence(score=0.90, source=ConfidenceSource.RULE),
                    evidence=["Spoken price without historical quote reference"],
                )
                return (
                    ResolutionResult(
                        resolution_id=resolution_id,
                        entity_type="price",
                        status=ResolutionStatus.RESOLVED,
                        query=query,
                        selected_entity_id=candidate.entity_id,
                        candidates=[candidate],
                        reason="Direct spoken price accepted for evaluation.",
                    ),
                    None,
                    resolved_price,
                )

            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="price",
                    status=ResolutionStatus.NOT_FOUND,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason="No pricing instruction or reference found in semantic state.",
                ),
                None,
                None,
            )

        # Historical reference requires resolved customer and product
        if customer is None or product is None:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="quote",
                    status=ResolutionStatus.INVALID,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason="Cannot resolve historical quote without a resolved customer and product.",
                ),
                None,
                None,
            )

        # Lookup quotes for customer and product
        quotes = self._quote_repo.find_quotes(
            customer_id=customer.customer.customer_id,
            product_id=product.product.product_id,
        )

        if not quotes:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="quote",
                    status=ResolutionStatus.NOT_FOUND,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason=f"No quotes found for customer '{customer.customer.name}' and product '{product.product.name}'.",
                ),
                None,
                None,
            )

        # If date resolved (e.g. from 'parso'), filter quotes matching that date
        matching_quotes = quotes
        if resolved_date is not None:
            date_matches = [q for q in quotes if q.quoted_on == resolved_date]
            if date_matches:
                matching_quotes = date_matches

        # Check for ambiguity
        if len(matching_quotes) > 1:
            candidates = [
                self._build_candidate(q, score=0.70, evidence=[f"Candidate quote {q.quote_id}"])
                for q in matching_quotes
            ]
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="quote",
                    status=ResolutionStatus.AMBIGUOUS,
                    query=query,
                    selected_entity_id=None,
                    candidates=candidates,
                    reason=f"Multiple quotes ({len(matching_quotes)}) match criteria; cannot resolve price safely.",
                ),
                None,
                None,
            )

        selected_quote = matching_quotes[0]
        candidate = self._build_candidate(
            selected_quote,
            score=0.99 if selected_quote.status == QuoteStatus.VALID else 0.50,
            evidence=[
                f"Quote on {selected_quote.quoted_on.isoformat()}",
                f"Price {selected_quote.unit_price} {selected_quote.currency}/{selected_quote.unit}",
                f"Status {selected_quote.status.value}",
            ],
        )

        # Safety Check: Expired Quote (Scenario D)
        if selected_quote.status != QuoteStatus.VALID:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="quote",
                    status=ResolutionStatus.INVALID,
                    query=query,
                    selected_entity_id=selected_quote.quote_id,
                    candidates=[candidate],
                    reason=f"Historical quote {selected_quote.quote_id} is {selected_quote.status.value} (valid until {selected_quote.valid_until}). Cannot apply blindly.",
                ),
                ResolvedQuote(
                    quote=selected_quote,
                    resolution_id=resolution_id,
                    resolved_at=resolved_at,
                ),
                None,
            )

        # Check spoken claim against quote unit price
        spoken_price = primary_price.amount if primary_price else None
        if spoken_price is not None and spoken_price != selected_quote.unit_price:
            candidate.evidence.append(
                f"Spoken price claim ({spoken_price}) differs from quote ({selected_quote.unit_price})"
            )

        resolved_quote = ResolvedQuote(
            quote=selected_quote,
            resolution_id=resolution_id,
            resolved_at=resolved_at,
        )

        resolved_price = ResolvedPrice(
            product_id=product.product.product_id,
            customer_id=customer.customer.customer_id,
            unit=selected_quote.unit,
            unit_price=selected_quote.unit_price,
            currency=selected_quote.currency,
            source_quote_id=selected_quote.quote_id,
            resolved_on=resolved_date or selected_quote.quoted_on,
        )

        return (
            ResolutionResult(
                resolution_id=resolution_id,
                entity_type="quote",
                status=ResolutionStatus.RESOLVED,
                query=query,
                selected_entity_id=selected_quote.quote_id,
                candidates=[candidate],
                reason=f"Resolved valid historical quote ({selected_quote.unit_price} {selected_quote.currency}/{selected_quote.unit}) from {selected_quote.quoted_on}.",
            ),
            resolved_quote,
            resolved_price,
        )

    def _build_candidate(
        self,
        quote: Quote,
        score: float,
        evidence: list[str],
    ) -> ResolutionCandidate:
        return ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=quote.quote_id,
            display_name=f"Quote {quote.quote_id} ({quote.unit_price} {quote.currency})",
            confidence=Confidence(
                score=score,
                source=ConfidenceSource.RULE,
            ),
            evidence=evidence,
            attributes={
                "quote_id": str(quote.quote_id),
                "unit_price": str(quote.unit_price),
                "currency": quote.currency,
                "quoted_on": quote.quoted_on.isoformat(),
                "status": quote.status.value,
            },
        )
