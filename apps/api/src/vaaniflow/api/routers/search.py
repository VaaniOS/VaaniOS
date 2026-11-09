from uuid import UUID

from fastapi import APIRouter

from vaaniflow.api.dependencies import ContainerDep

router = APIRouter(tags=["Search"])


@router.get("/customers/search")
def search_customers(
    container: ContainerDep,
    query: str = "",
) -> list[dict]:
    results = container.repositories.customers.search(query=query)
    return [
        {
            "customer_id": str(c.customer_id),
            "name": c.name,
            "aliases": c.aliases,
            "city": c.city,
            "tax_id": c.tax_id,
        }
        for c in results
    ]


@router.get("/products/search")
def search_products(
    container: ContainerDep,
    query: str = "",
) -> list[dict]:
    results = container.repositories.products.search(query=query)
    return [
        {
            "product_id": str(p.product_id),
            "name": p.name,
            "sku": p.sku,
            "category": p.category,
            "unit": p.unit,
        }
        for p in results
    ]


@router.get("/quotes/search")
def search_quotes(
    container: ContainerDep,
    customer_id: UUID | None = None,
    product_id: UUID | None = None,
) -> list[dict]:
    all_quotes = container.repositories.quotes.list_all()
    filtered = all_quotes
    if customer_id:
        filtered = [q for q in filtered if q.customer_id == customer_id]
    if product_id:
        filtered = [q for q in filtered if q.product_id == product_id]

    return [
        {
            "quote_id": str(q.quote_id),
            "customer_id": str(q.customer_id),
            "product_id": str(q.product_id),
            "unit_price": str(q.unit_price),
            "unit": q.unit,
            "status": q.status.value,
            "quoted_on": q.quoted_on.isoformat(),
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        }
        for q in filtered
    ]


@router.get("/inventory/search")
def search_inventory(
    container: ContainerDep,
    product_id: UUID | None = None,
    warehouse_id: UUID | None = None,
) -> list[dict]:
    all_inv = container.repositories.inventory.list_all()
    filtered = all_inv
    if product_id:
        filtered = [i for i in filtered if i.product_id == product_id]
    if warehouse_id:
        filtered = [i for i in filtered if i.warehouse_id == warehouse_id]

    return [
        {
            "inventory_id": str(i.inventory_id),
            "product_id": str(i.product_id),
            "warehouse_id": str(i.warehouse_id),
            "available_quantity": i.available_quantity,
            "reserved_quantity": i.reserved_quantity,
        }
        for i in filtered
    ]
