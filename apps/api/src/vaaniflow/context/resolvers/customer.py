from datetime import datetime
from uuid import uuid4

from vaaniflow.application.ports.business_data import CustomerRepository
from vaaniflow.context.models.business_context import ResolvedCustomer
from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.models.customer import Customer
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import SemanticEntity


class CustomerResolver:
    """
    Deterministic business customer resolver.

    Maps a spoken/extracted customer mention to an authoritative Customer record.
    If multiple customers match, records ambiguity explicitly and never guesses.
    """

    def __init__(self, customer_repo: CustomerRepository) -> None:
        self._customer_repo = customer_repo

    def resolve(
        self,
        *,
        semantic_customer: SemanticEntity | None,
        resolved_at: datetime,
    ) -> tuple[ResolutionResult, ResolvedCustomer | None]:
        resolution_id = uuid4()

        if semantic_customer is None:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="customer",
                    status=ResolutionStatus.NOT_FOUND,
                    query="",
                    selected_entity_id=None,
                    candidates=[],
                    reason="No customer entity mentioned in semantic state.",
                ),
                None,
            )

        query = semantic_customer.normalized_text or semantic_customer.surface_text
        matches = self._customer_repo.search(query=query)

        if not matches:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="customer",
                    status=ResolutionStatus.NOT_FOUND,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason=f"No customer found matching query '{query}'.",
                ),
                None,
            )

        # Check for single exact name match among candidates
        exact_matches = [
            c
            for c in matches
            if c.name.lower() == query.lower() or any(a.lower() == query.lower() for a in c.aliases)
        ]

        # If exactly one exact match exists, resolve to it
        if len(exact_matches) == 1:
            selected = exact_matches[0]
            candidate = self._build_candidate(
                selected, score=0.98, evidence=["Exact name/alias match"]
            )
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="customer",
                    status=ResolutionStatus.RESOLVED,
                    query=query,
                    selected_entity_id=selected.customer_id,
                    candidates=[candidate],
                    reason=f"Resolved unique customer '{selected.name}'.",
                ),
                ResolvedCustomer(
                    customer=selected,
                    resolution_id=resolution_id,
                    resolved_at=resolved_at,
                ),
            )

        # If multiple candidates match (ambiguous)
        if len(matches) > 1:
            candidates = [
                self._build_candidate(
                    c,
                    score=0.75,
                    evidence=[f"Partial match on customer '{c.name}'"],
                )
                for c in matches
            ]
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="customer",
                    status=ResolutionStatus.AMBIGUOUS,
                    query=query,
                    selected_entity_id=None,
                    candidates=candidates,
                    reason=f"Multiple customer candidates match '{query}': {', '.join(c.name for c in matches)}.",
                ),
                None,
            )

        # Exactly 1 partial match
        selected = matches[0]
        candidate = self._build_candidate(selected, score=0.90, evidence=["Unique search match"])
        return (
            ResolutionResult(
                resolution_id=resolution_id,
                entity_type="customer",
                status=ResolutionStatus.RESOLVED,
                query=query,
                selected_entity_id=selected.customer_id,
                candidates=[candidate],
                reason=f"Resolved customer '{selected.name}' via unique match.",
            ),
            ResolvedCustomer(
                customer=selected,
                resolution_id=resolution_id,
                resolved_at=resolved_at,
            ),
        )

    def _build_candidate(
        self,
        customer: Customer,
        score: float,
        evidence: list[str],
    ) -> ResolutionCandidate:
        return ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=customer.customer_id,
            display_name=customer.name,
            confidence=Confidence(
                score=score,
                source=ConfidenceSource.RULE,
            ),
            evidence=evidence,
            attributes={
                "tax_id": customer.tax_id,
                "city": customer.city,
                "status": customer.status.value,
            },
        )
