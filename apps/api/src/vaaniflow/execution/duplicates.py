"""
Business-level duplicate order detection (P2-A).

Technical idempotency (one key per plan step) prevents a retried call from
writing twice. It does not stop a second, semantically identical request
from creating a second order. This check compares the business identity of
the order a plan would create with existing orders, deterministically:

    customer · currency · line items (product, quantity, unit, unit price)
    · delivery address when both sides have one

An equivalent order that is still open (not cancelled, failed or completed)
is a duplicate whenever it was placed. An equivalent order that is already
completed (fulfilled, or dispatched) is only a duplicate on the same business
date; later, it is ordinary repeat business. Cancelled and failed orders are
never duplicates. If the order records cannot be read, the result is
DUPLICATE_CHECK_UNAVAILABLE and the caller must not create the order.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field

from vaaniflow.domain.models.dispatch import DispatchStatus
from vaaniflow.domain.models.order import Order, OrderStatus
from vaaniflow.domain.schemas.common import DomainSchema
from vaaniflow.execution.plan import ExecutionPlan
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories

_NEVER_DUPLICATE = frozenset({OrderStatus.CANCELLED, OrderStatus.FAILED})


class DuplicateStatus(StrEnum):
    NO_DUPLICATE = "NO_DUPLICATE"
    DUPLICATE_FOUND = "DUPLICATE_FOUND"
    DUPLICATE_CHECK_UNAVAILABLE = "DUPLICATE_CHECK_UNAVAILABLE"


class DuplicateCheck(DomainSchema):
    status: DuplicateStatus
    reason: str = Field(min_length=1)
    duplicate_order_ids: list[UUID] = Field(default_factory=list)
    business_key: dict[str, Any] = Field(default_factory=dict)


def _line_key(items: list[Any]) -> Counter[tuple[str, int, str, str]]:
    keys: Counter[tuple[str, int, str, str]] = Counter()
    for item in items:
        if isinstance(item, dict):
            product, qty, unit, price = (
                item["product_id"],
                item["quantity"],
                item["unit"],
                item["unit_price"],
            )
        else:
            product, qty, unit, price = item.product_id, item.quantity, item.unit, item.unit_price
        keys[(str(product), int(qty), str(unit), str(Decimal(str(price)).normalize()))] += 1
    return keys


def check_duplicate_order(
    *,
    plan: ExecutionPlan,
    repositories: SyntheticRepositories,
    now: datetime,
    timezone: str = "Asia/Kolkata",
) -> DuplicateCheck:
    order_call = next((c for c in plan.tool_calls if c.tool_name == "create_order"), None)
    if order_call is None:
        return DuplicateCheck(
            status=DuplicateStatus.NO_DUPLICATE, reason="The plan creates no order."
        )

    args = order_call.arguments
    customer_id = UUID(str(args["customer_id"]))
    address = args.get("delivery_address")
    lines = _line_key(args["items"])
    business_key: dict[str, Any] = {
        "customer_id": str(customer_id),
        "currency": args["currency"],
        "items": sorted(lines.elements()),
        "delivery_address": address,
    }

    tz = ZoneInfo(timezone)
    today: date = now.astimezone(tz).date()
    try:
        existing = repositories.orders.list_by_customer(customer_id=customer_id)
        dispatched = {order.order_id: _is_dispatched(repositories, order) for order in existing}
    except Exception as exc:  # noqa: BLE001 - an unreadable order store is not "no duplicate"
        return DuplicateCheck(
            status=DuplicateStatus.DUPLICATE_CHECK_UNAVAILABLE,
            reason=f"Existing orders could not be read ({type(exc).__name__}: {exc}).",
            business_key=business_key,
        )

    matches: list[Order] = []
    for order in existing:
        if order.status in _NEVER_DUPLICATE:
            continue
        if order.currency != args["currency"] or _line_key(order.items) != lines:
            continue
        if address and order.delivery_address and order.delivery_address != address:
            continue  # a different destination is a different business operation
        completed = order.status is OrderStatus.FULFILLED or dispatched[order.order_id]
        same_day = order.created_at.astimezone(tz).date() == today
        if not completed or same_day:
            matches.append(order)

    if not matches:
        return DuplicateCheck(
            status=DuplicateStatus.NO_DUPLICATE,
            reason="No open or same-day equivalent order exists.",
            business_key=business_key,
        )
    described = ", ".join(
        f"{o.order_id} ({o.status.value}{', dispatched' if dispatched[o.order_id] else ''}, "
        f"created {o.created_at.astimezone(tz).date().isoformat()})"
        for o in matches
    )
    return DuplicateCheck(
        status=DuplicateStatus.DUPLICATE_FOUND,
        reason=f"An equivalent order already exists: {described}.",
        duplicate_order_ids=[o.order_id for o in matches],
        business_key=business_key,
    )


def _is_dispatched(repositories: SyntheticRepositories, order: Order) -> bool:
    dispatch = repositories.dispatches.get_by_order_id(order_id=order.order_id)
    return dispatch is not None and dispatch.status is DispatchStatus.DISPATCHED
