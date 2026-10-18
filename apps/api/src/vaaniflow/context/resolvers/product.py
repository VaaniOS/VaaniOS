from datetime import datetime
from uuid import uuid4

from vaaniflow.application.ports.business_data import ProductRepository
from vaaniflow.context.models.business_context import ResolvedProduct
from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.models.product import Product
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import SemanticEntity


class ProductResolver:
    """
    Deterministic catalog product resolver.

    Maps a spoken product mention to an authoritative Product SKU.
    When multiple SKUs match a generic term (e.g., 'Ultratech cement'),
    flags ambiguity explicitly.
    """

    def __init__(self, product_repo: ProductRepository) -> None:
        self._product_repo = product_repo

    def resolve(
        self,
        *,
        semantic_product: SemanticEntity | None,
        resolved_at: datetime,
    ) -> tuple[ResolutionResult, ResolvedProduct | None]:
        resolution_id = uuid4()

        if semantic_product is None:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="product",
                    status=ResolutionStatus.NOT_FOUND,
                    query="<product_unspecified>",
                    selected_entity_id=None,
                    candidates=[],
                    reason="No product entity in item.",
                ),
                None,
            )

        query = semantic_product.normalized_text or semantic_product.surface_text

        # First check if query matches an exact SKU
        by_sku = self._product_repo.get_by_sku(sku=query)
        if by_sku is not None:
            candidate = self._build_candidate(by_sku, score=1.0, evidence=["Exact SKU match"])
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="product",
                    status=ResolutionStatus.RESOLVED,
                    query=query,
                    selected_entity_id=by_sku.product_id,
                    candidates=[candidate],
                    reason=f"Resolved product by exact SKU '{by_sku.sku}'.",
                ),
                ResolvedProduct(
                    product=by_sku,
                    resolution_id=resolution_id,
                    resolved_at=resolved_at,
                ),
            )

        matches = self._product_repo.search(query=query)
        if not matches:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="product",
                    status=ResolutionStatus.NOT_FOUND,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason=f"No product found matching '{query}'.",
                ),
                None,
            )

        # Check for unique exact name/alias matches
        exact_matches = [
            p
            for p in matches
            if p.name.lower() == query.lower() or any(a.lower() == query.lower() for a in p.aliases)
        ]

        if len(exact_matches) == 1:
            selected = exact_matches[0]
            candidate = self._build_candidate(
                selected, score=0.98, evidence=["Unique exact name/alias match"]
            )
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="product",
                    status=ResolutionStatus.RESOLVED,
                    query=query,
                    selected_entity_id=selected.product_id,
                    candidates=[candidate],
                    reason=f"Resolved product '{selected.name}' ({selected.sku}).",
                ),
                ResolvedProduct(
                    product=selected,
                    resolution_id=resolution_id,
                    resolved_at=resolved_at,
                ),
            )

        # If multiple matches exist (ambiguous SKU selection)
        if len(matches) > 1:
            candidates = [
                self._build_candidate(
                    p,
                    score=0.75,
                    evidence=[f"Catalog candidate '{p.name}' ({p.sku})"],
                )
                for p in matches
            ]
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="product",
                    status=ResolutionStatus.AMBIGUOUS,
                    query=query,
                    selected_entity_id=None,
                    candidates=candidates,
                    reason=f"Multiple product SKUs match '{query}': {', '.join(p.sku for p in matches)}.",
                ),
                None,
            )

        selected = matches[0]
        candidate = self._build_candidate(selected, score=0.90, evidence=["Unique search match"])
        return (
            ResolutionResult(
                resolution_id=resolution_id,
                entity_type="product",
                status=ResolutionStatus.RESOLVED,
                query=query,
                selected_entity_id=selected.product_id,
                candidates=[candidate],
                reason=f"Resolved product '{selected.name}' ({selected.sku}).",
            ),
            ResolvedProduct(
                product=selected,
                resolution_id=resolution_id,
                resolved_at=resolved_at,
            ),
        )

    def _build_candidate(
        self,
        product: Product,
        score: float,
        evidence: list[str],
    ) -> ResolutionCandidate:
        return ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=product.product_id,
            display_name=f"{product.name} ({product.sku})",
            confidence=Confidence(
                score=score,
                source=ConfidenceSource.RULE,
            ),
            evidence=evidence,
            attributes={
                "sku": product.sku,
                "unit": product.unit,
                "brand": product.brand,
                "status": product.status.value,
            },
        )
