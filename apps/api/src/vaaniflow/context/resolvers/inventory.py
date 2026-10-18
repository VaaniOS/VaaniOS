from datetime import datetime
from uuid import uuid4

from vaaniflow.application.ports.business_data import InventoryRepository
from vaaniflow.context.models.business_context import (
    ResolvedInventory,
    ResolvedProduct,
)
from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.models.inventory import Inventory
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import SemanticQuantity


class InventoryResolver:
    """
    Deterministic inventory stock resolver.

    Retrieves stock levels (available vs reserved) for resolved products
    and assesses whether requested quantities can be fulfilled.
    """

    def __init__(self, inventory_repo: InventoryRepository) -> None:
        self._inventory_repo = inventory_repo

    def resolve(
        self,
        *,
        product: ResolvedProduct | None,
        quantity: SemanticQuantity | None,
        resolved_at: datetime,
    ) -> tuple[ResolutionResult, list[ResolvedInventory]]:
        resolution_id = uuid4()

        if product is None:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="inventory",
                    status=ResolutionStatus.INVALID,
                    query="<product_unspecified>",
                    selected_entity_id=None,
                    candidates=[],
                    reason="Cannot check inventory without a resolved product.",
                ),
                [],
            )

        query = product.product.sku
        records = self._inventory_repo.get_by_product(product_id=product.product.product_id)

        if not records:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="inventory",
                    status=ResolutionStatus.NOT_FOUND,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason=f"No inventory records found for product '{product.product.sku}'.",
                ),
                [],
            )

        resolved_inventories = [
            ResolvedInventory(
                inventory=record,
                resolution_id=resolution_id,
                resolved_at=resolved_at,
            )
            for record in records
        ]

        total_available = sum(r.available_quantity for r in records)
        total_reserved = sum(r.reserved_quantity for r in records)
        net_stock = total_available - total_reserved

        evidence = [
            f"Total available: {total_available}",
            f"Total reserved: {total_reserved}",
            f"Net sellable stock: {net_stock}",
        ]

        # Check if requested quantity exceeds stock
        req_val = int(quantity.value) if quantity else None
        if req_val is not None:
            evidence.append(f"Requested quantity: {req_val}")
            if req_val > net_stock:
                evidence.append(
                    f"INVENTORY_SHORTAGE: Requested {req_val} exceeds net stock {net_stock}"
                )

        candidates = [self._build_candidate(r, net_stock, evidence) for r in records]

        return (
            ResolutionResult(
                resolution_id=resolution_id,
                entity_type="inventory",
                status=ResolutionStatus.RESOLVED,
                query=query,
                selected_entity_id=records[0].inventory_id,
                candidates=candidates,
                reason=f"Inventory resolved: {net_stock} net units available for {product.product.sku}.",
            ),
            resolved_inventories,
        )

    def _build_candidate(
        self,
        inventory: Inventory,
        net_stock: int,
        evidence: list[str],
    ) -> ResolutionCandidate:
        return ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=inventory.inventory_id,
            display_name=f"Inventory at warehouse {inventory.warehouse_id} (Net: {inventory.available_quantity - inventory.reserved_quantity})",
            confidence=Confidence(score=1.0, source=ConfidenceSource.RULE),
            evidence=list(evidence),
            attributes={
                "available_quantity": inventory.available_quantity,
                "reserved_quantity": inventory.reserved_quantity,
                "net_stock": inventory.available_quantity - inventory.reserved_quantity,
                "warehouse_id": str(inventory.warehouse_id),
            },
        )
