from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid4

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
from vaaniflow.domain.models.quote import Quote
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    PriceSource,
    ReferenceType,
    SemanticPrice,
    SemanticReference,
)

HISTORICAL_REFERENCE_TYPES = frozenset(
    {ReferenceType.HISTORICAL_PRICE, ReferenceType.HISTORICAL_QUOTE}
)

_Resolution = tuple[ResolutionResult, ResolvedQuote | None, ResolvedPrice | None]


class _ResultFactory(Protocol):
    """Signature of the per-resolution result() builder."""

    def __call__(
        self,
        status: ResolutionStatus,
        reason: str,
        *,
        entity_type: str = "quote",
        selected: UUID | None = None,
        candidates: list[ResolutionCandidate] | None = None,
    ) -> ResolutionResult: ...


class PriceQuoteResolver:
    """
    Deterministic quote and price resolver (System-Design 06 §6.6).

    Pricing authority rule: the only business-authoritative execution price is
    the unit price of exactly one quote for the resolved customer and product
    that is applicable on the business date (status VALID and the business
    date inside [quoted_on, valid_until]). A spoken amount is a claim that is
    compared with that quote; it never becomes the price on its own.

    A historical reference ("rate wahi jo parso bataya tha") is constrained by
    the temporal expression the semantic layer linked to it: only quotes given
    on that date are candidates. If none exists, no other date is substituted.
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
        business_date: date | None = None,
        anchor_surface: str | None = None,
        anchor_unresolved: str | None = None,
    ) -> _Resolution:
        """
        Args:
            resolved_date: calendar date of the temporal expression linked to
                the historical price reference (e.g. "parso"), if any.
            business_date: date on which the transaction would execute; quote
                validity is checked against it (defaults to resolved_at's date).
            anchor_surface: surface text of the linked temporal expression.
            anchor_unresolved: set when the reference is linked to a temporal
                expression that could not be resolved to a date.
        """
        resolution_id = uuid4()
        today = business_date or resolved_at.date()
        primary_price = pricing[0] if pricing else None
        spoken_amount = primary_price.amount if primary_price else None

        has_historical_ref = any(
            ref.reference_type in HISTORICAL_REFERENCE_TYPES for ref in references
        ) or (
            primary_price is not None
            and primary_price.source
            in {PriceSource.HISTORICAL_REFERENCE, PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE}
        )
        query = primary_price.surface_text if primary_price else "historical_rate"

        def result(
            status: ResolutionStatus,
            reason: str,
            *,
            entity_type: str = "quote",
            selected: UUID | None = None,
            candidates: list[ResolutionCandidate] | None = None,
        ) -> ResolutionResult:
            return ResolutionResult(
                resolution_id=resolution_id,
                entity_type=entity_type,
                status=status,
                query=query,
                selected_entity_id=selected,
                candidates=candidates or [],
                reason=reason,
            )

        if not has_historical_ref and spoken_amount is None:
            return (
                result(
                    ResolutionStatus.NOT_FOUND,
                    "No pricing instruction or reference found in semantic state.",
                    entity_type="price",
                ),
                None,
                None,
            )

        if customer is None or product is None:
            return (
                result(
                    ResolutionStatus.INVALID,
                    "Cannot resolve a price without a resolved customer and product.",
                ),
                None,
                None,
            )

        names = f"customer '{customer.customer.name}' and product '{product.product.name}'"
        quotes = self._quote_repo.find_quotes(
            customer_id=customer.customer.customer_id,
            product_id=product.product.product_id,
        )

        if has_historical_ref:
            if anchor_unresolved is not None:
                return (
                    result(
                        ResolutionStatus.INVALID,
                        f"The referenced rate is tied to '{anchor_unresolved}', which could not "
                        "be resolved to a calendar date; no quote was selected.",
                    ),
                    None,
                    None,
                )

            pool = quotes
            if resolved_date is not None:
                pool = [q for q in quotes if q.quoted_on == resolved_date]
                if not pool:
                    others = sorted({q.quoted_on.isoformat() for q in quotes})
                    elsewhere = (
                        f" Quotes exist on other dates ({', '.join(others)}) and were not "
                        "substituted."
                        if others
                        else ""
                    )
                    return (
                        result(
                            ResolutionStatus.NOT_FOUND,
                            f"No quote for {names} was given on {resolved_date.isoformat()} "
                            f"('{anchor_surface or resolved_date.isoformat()}').{elsewhere}",
                            candidates=[
                                self._candidate(q, 0.10, ["Different quote date; not eligible"])
                                for q in quotes
                            ],
                        ),
                        None,
                        None,
                    )
            if not pool:
                return (
                    result(ResolutionStatus.NOT_FOUND, f"No quotes found for {names}."),
                    None,
                    None,
                )
            return self._select(
                pool=pool,
                today=today,
                spoken_amount=spoken_amount,
                customer=customer,
                product=product,
                resolution_id=resolution_id,
                resolved_at=resolved_at,
                result=result,
                context="referenced",
            )

        # Spoken price only: it is a claim; the authority is an applicable quote.
        applicable = [q for q in quotes if q.is_applicable_on(today)]
        if not applicable:
            return (
                result(
                    ResolutionStatus.NOT_FOUND,
                    f"Spoken price {spoken_amount} cannot be used: no quote for {names} is "
                    f"valid on {today.isoformat()}. A spoken price is a claim, not "
                    "business-authoritative pricing.",
                    entity_type="price",
                ),
                None,
                None,
            )
        return self._select(
            pool=applicable,
            today=today,
            spoken_amount=spoken_amount,
            customer=customer,
            product=product,
            resolution_id=resolution_id,
            resolved_at=resolved_at,
            result=result,
            context="current",
        )

    def _select(
        self,
        *,
        pool: list[Quote],
        today: date,
        spoken_amount: object,
        customer: ResolvedCustomer,
        product: ResolvedProduct,
        resolution_id: UUID,
        resolved_at: datetime,
        result: _ResultFactory,
        context: str,
    ) -> _Resolution:
        applicable = [q for q in pool if q.is_applicable_on(today)]

        if not applicable:
            # The referenced quote exists but cannot price a transaction today.
            stale = max(pool, key=lambda q: q.quoted_on)
            return (
                result(
                    ResolutionStatus.INVALID,
                    f"Historical quote {stale.quote_id} is {stale.status.value} "
                    f"(quoted {stale.quoted_on.isoformat()}, valid until {stale.valid_until}) "
                    f"and not applicable on {today.isoformat()}. Cannot apply blindly.",
                    selected=stale.quote_id,
                    candidates=[self._candidate(stale, 0.50, ["Not applicable on business date"])],
                ),
                ResolvedQuote(quote=stale, resolution_id=resolution_id, resolved_at=resolved_at),
                None,
            )

        if len(applicable) > 1:
            return (
                result(
                    ResolutionStatus.AMBIGUOUS,
                    f"Multiple {context} quotes ({len(applicable)}) match; cannot resolve "
                    "price safely.",
                    candidates=[
                        self._candidate(q, 0.70, [f"Candidate quote {q.quote_id}"])
                        for q in applicable
                    ],
                ),
                None,
                None,
            )

        quote = applicable[0]
        evidence = [
            f"Quote on {quote.quoted_on.isoformat()}",
            f"Valid until {quote.valid_until.isoformat() if quote.valid_until else 'open'}",
            f"Price {quote.unit_price} {quote.currency}/{quote.unit}",
            f"Status {quote.status.value}, applicable on {today.isoformat()}",
        ]
        if spoken_amount is not None and spoken_amount != quote.unit_price:
            evidence.append(
                f"Spoken price claim ({spoken_amount}) differs from quote ({quote.unit_price})"
            )
        candidate = self._candidate(quote, 0.99, evidence)

        return (
            result(
                ResolutionStatus.RESOLVED,
                f"Resolved {context} quote ({quote.unit_price} {quote.currency}/{quote.unit}) "
                f"from {quote.quoted_on.isoformat()}, applicable on {today.isoformat()}.",
                selected=quote.quote_id,
                candidates=[candidate],
            ),
            ResolvedQuote(quote=quote, resolution_id=resolution_id, resolved_at=resolved_at),
            ResolvedPrice(
                product_id=product.product.product_id,
                customer_id=customer.customer.customer_id,
                unit=quote.unit,
                unit_price=quote.unit_price,
                currency=quote.currency,
                source_quote_id=quote.quote_id,
                resolved_on=today,
            ),
        )

    def _candidate(self, quote: Quote, score: float, evidence: list[str]) -> ResolutionCandidate:
        return ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=quote.quote_id,
            display_name=f"Quote {quote.quote_id} ({quote.unit_price} {quote.currency})",
            confidence=Confidence(score=score, source=ConfidenceSource.RULE),
            evidence=evidence,
            attributes={
                "quote_id": str(quote.quote_id),
                "unit_price": str(quote.unit_price),
                "currency": quote.currency,
                "quoted_on": quote.quoted_on.isoformat(),
                "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
                "status": quote.status.value,
            },
        )
