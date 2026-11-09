"""
Explicit execution plan derived from the user's requested actions.

The plan is the only thing that may be executed after approval:

    requested_actions − negated_actions
        → executable actions
        → tool calls with arguments taken from grounded business context
        → approval bound to (run, plan fingerprint, business snapshot)

No tool is planned for an action the user did not request, no tool is
planned for a negated action, and no argument is ever filled from a default:
a missing business fact raises PlanningError so the run fails safely.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from vaaniflow.context.models.business_context import BusinessContext
from vaaniflow.domain.models.tax import TaxCalculation
from vaaniflow.domain.schemas.common import DomainSchema
from vaaniflow.domain.schemas.semantic import RequestedActionType, SemanticState
from vaaniflow.domain.schemas.understand import UnderstandResult

# Write tools each requested action needs, in execution order.
ACTION_TOOLS: dict[RequestedActionType, tuple[str, ...]] = {
    RequestedActionType.CREATE_ORDER: ("create_order",),
    RequestedActionType.DISPATCH: ("create_order", "dispatch_order"),
    RequestedActionType.CREATE_INVOICE_DRAFT: ("create_order", "create_invoice_draft"),
}
TOOL_ORDER: tuple[str, ...] = ("create_order", "create_invoice_draft", "dispatch_order")

# Answered from already-resolved business context; no side effects.
READ_ACTIONS = frozenset({RequestedActionType.CHECK_PRICE, RequestedActionType.CHECK_INVENTORY})

# Satisfied by the approval workflow itself (an approval request is created).
APPROVAL_ACTIONS = frozenset({RequestedActionType.REQUEST_APPROVAL})

# Requested but not implemented by any tool. Never silently dropped.
# (SEND_NOTIFICATION, CANCEL_ORDER, UPDATE_ORDER, ...)


class PlanningError(Exception):
    """A required business fact is missing; the plan cannot be built safely."""


class PlannedToolCall(DomainSchema):
    tool_name: str = Field(min_length=1)
    action_types: list[RequestedActionType]
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on_order: bool = False


class ExecutionPlan(DomainSchema):
    plan_id: UUID
    run_id: UUID
    executable_actions: list[RequestedActionType]
    excluded_negated_actions: list[RequestedActionType] = Field(default_factory=list)
    read_actions: list[RequestedActionType] = Field(default_factory=list)
    unsupported_actions: list[RequestedActionType] = Field(default_factory=list)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)
    snapshot_version: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)

    @property
    def has_writes(self) -> bool:
        return bool(self.tool_calls)

    @property
    def tool_names(self) -> list[str]:
        return [call.tool_name for call in self.tool_calls]


class PendingExecution(DomainSchema):
    """A plan awaiting explicit approval, with the UnderstandResult it came from."""

    approval_id: UUID
    plan: ExecutionPlan
    understand_result: UnderstandResult
    created_at: datetime


class StepStatus(StrEnum):
    """Outcome of one planned tool call, as established by evidence."""

    VERIFIED = "VERIFIED"  # executed and confirmed by read-back of business state
    FAILED = "FAILED"  # definitively not performed
    UNKNOWN = "UNKNOWN"  # may or may not have happened, or could not be verified
    NOT_ATTEMPTED = "NOT_ATTEMPTED"  # skipped because an earlier step did not verify


class StepOutcome(DomainSchema):
    """Per-tool result of executing an approved plan. Never flattened away."""

    tool_name: str = Field(min_length=1)
    status: StepStatus
    execution_status: str | None = None
    verification_status: str | None = None
    entity_id: str | None = None
    error_code: str | None = None
    message: str = Field(min_length=1)
    reconciled: bool = False


def expected_state_for(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Business state a write must leave behind, derived only from the approved
    plan arguments. Read-back verification compares the stored record with it.
    """
    items = arguments.get("items", [])
    if tool_name == "create_order":
        expected: dict[str, Any] = {
            "customer_id": arguments["customer_id"],
            "currency": arguments["currency"],
            "items_count": len(items),
            "subtotal": str(sum(Decimal(str(i["line_total"])) for i in items)),
            "status": "DRAFT",
        }
        if arguments.get("delivery_address"):
            expected["delivery_address"] = arguments["delivery_address"]
        return expected
    if tool_name == "create_invoice_draft":
        return {
            "order_id": arguments["order_id"],
            "customer_id": arguments["customer_id"],
            "currency": arguments["currency"],
            "subtotal": arguments["subtotal"],
            "tax_total": arguments["tax_total"],
            "total": arguments["total"],
            "items_count": len(items),
            "status": "DRAFT",
        }
    if tool_name == "dispatch_order":
        return {
            "order_id": arguments["order_id"],
            "customer_id": arguments["customer_id"],
            "warehouse_id": arguments["warehouse_id"],
            "delivery_address": arguments["delivery_address"],
            "status": "DISPATCHED",
        }
    raise PlanningError(f"No read-back contract is defined for tool '{tool_name}'.")


def split_actions(
    semantic_state: SemanticState,
) -> tuple[list[RequestedActionType], list[RequestedActionType]]:
    """(executable requested actions, negated actions) — a negated type is never executable."""
    negated = [action.action_type for action in semantic_state.negated_actions]
    executable: list[RequestedActionType] = []
    for action in semantic_state.requested_actions:
        if action.action_type in negated or action.action_type in executable:
            continue
        executable.append(action.action_type)
    return executable, negated


def business_snapshot_version(
    business_context: BusinessContext,
    tax_calculation: TaxCalculation | None,
) -> str:
    """
    Deterministic hash of the business facts a decision relies on.

    Resolution metadata (resolution ids, resolved_at timestamps, the run date
    used to resolve relative dates) is excluded, so unchanged business state
    yields the same version at any later time.
    """
    price = business_context.resolved_price
    facts = {
        "customer": business_context.customer.customer.model_dump(mode="json")
        if business_context.customer
        else None,
        "products": [p.product.model_dump(mode="json") for p in business_context.products],
        "quotes": [q.quote.model_dump(mode="json") for q in business_context.quotes],
        "inventory": [i.inventory.model_dump(mode="json") for i in business_context.inventory],
        "price": {
            "product_id": str(price.product_id),
            "customer_id": str(price.customer_id),
            "unit": price.unit,
            "unit_price": str(price.unit_price),
            "currency": price.currency,
            "source_quote_id": str(price.source_quote_id) if price.source_quote_id else None,
        }
        if price
        else None,
        "tax": tax_calculation.model_dump(mode="json") if tax_calculation else None,
    }
    encoded = json.dumps(facts, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _fingerprint(
    executable: list[RequestedActionType],
    unsupported: list[RequestedActionType],
    tool_calls: list[PlannedToolCall],
) -> str:
    payload = {
        "executable": [a.value for a in executable],
        "unsupported": [a.value for a in unsupported],
        "tool_calls": [
            {"tool": call.tool_name, "arguments": call.arguments} for call in tool_calls
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def build_plan(
    *,
    run_id: UUID,
    semantic_state: SemanticState,
    business_context: BusinessContext,
    tax_calculation: TaxCalculation | None,
) -> ExecutionPlan:
    """Build the plan for exactly what was requested. Raises PlanningError."""
    executable, negated = split_actions(semantic_state)

    reads = [a for a in executable if a in READ_ACTIONS]
    unsupported = [
        a
        for a in executable
        if a not in ACTION_TOOLS and a not in READ_ACTIONS and a not in APPROVAL_ACTIONS
    ]
    tools = {tool for action in executable for tool in ACTION_TOOLS.get(action, ())}
    tool_calls = _tool_calls(
        tools=[t for t in TOOL_ORDER if t in tools],
        executable=executable,
        semantic_state=semantic_state,
        business_context=business_context,
        tax_calculation=tax_calculation,
    )

    return ExecutionPlan(
        plan_id=uuid4(),
        run_id=run_id,
        executable_actions=executable,
        excluded_negated_actions=negated,
        read_actions=reads,
        unsupported_actions=unsupported,
        tool_calls=tool_calls,
        snapshot_version=business_snapshot_version(business_context, tax_calculation),
        fingerprint=_fingerprint(executable, unsupported, tool_calls),
    )


def _actions_for(tool: str, executable: list[RequestedActionType]) -> list[RequestedActionType]:
    return [a for a in executable if tool in ACTION_TOOLS.get(a, ())]


def _tool_calls(
    *,
    tools: list[str],
    executable: list[RequestedActionType],
    semantic_state: SemanticState,
    business_context: BusinessContext,
    tax_calculation: TaxCalculation | None,
) -> list[PlannedToolCall]:
    if not tools:
        return []

    if len(semantic_state.items) != 1:
        raise PlanningError("Exactly one line item is required to plan business writes.")
    if business_context.customer is None:
        raise PlanningError("Customer is not resolved against business records.")
    if len(business_context.products) != 1:
        raise PlanningError("Product is not uniquely resolved against the catalog.")
    if business_context.resolved_price is None:
        raise PlanningError("No unit price was resolved from business records.")
    if business_context.resolved_price.source_quote_id is None:
        raise PlanningError("The unit price is not backed by a business quote.")

    quantity = semantic_state.items[0].quantity
    if quantity is None or quantity.unit is None:
        raise PlanningError("Quantity and unit are required.")
    if quantity.value != quantity.value.to_integral_value():
        raise PlanningError(f"Quantity {quantity.value} is not a whole number of units.")

    customer = business_context.customer.customer
    product = business_context.products[0].product
    price = business_context.resolved_price
    qty = int(quantity.value)
    line_total = price.unit_price * Decimal(qty)

    item = {
        "product_id": str(product.product_id),
        "quantity": qty,
        "unit": quantity.unit,
        "unit_price": str(price.unit_price),
        "line_total": str(line_total),
    }

    calls: list[PlannedToolCall] = []
    dispatching = "dispatch_order" in tools

    if dispatching and not customer.address:
        raise PlanningError(f"Customer '{customer.name}' has no delivery address on record.")

    if "create_order" in tools:
        order_args: dict[str, Any] = {
            "customer_id": str(customer.customer_id),
            "currency": price.currency,
            "items": [item],
        }
        if dispatching:
            order_args["delivery_address"] = customer.address
        calls.append(
            PlannedToolCall(
                tool_name="create_order",
                action_types=_actions_for("create_order", executable),
                arguments=order_args,
            )
        )

    if "create_invoice_draft" in tools:
        if tax_calculation is None:
            raise PlanningError("Tax could not be calculated by the business rules layer.")
        calls.append(
            PlannedToolCall(
                tool_name="create_invoice_draft",
                action_types=_actions_for("create_invoice_draft", executable),
                arguments={
                    "customer_id": str(customer.customer_id),
                    "currency": price.currency,
                    "subtotal": str(tax_calculation.taxable_amount),
                    "tax_total": str(tax_calculation.total_tax),
                    "total": str(tax_calculation.total_amount),
                    "items": [item],
                },
                depends_on_order=True,
            )
        )

    if dispatching:
        warehouse_id = next(
            (
                record.inventory.warehouse_id
                for record in business_context.inventory
                if record.inventory.product_id == product.product_id
                and record.inventory.available_quantity - record.inventory.reserved_quantity >= qty
            ),
            None,
        )
        if warehouse_id is None:
            raise PlanningError(f"No warehouse holds {qty} sellable units of {product.sku}.")
        calls.append(
            PlannedToolCall(
                tool_name="dispatch_order",
                action_types=_actions_for("dispatch_order", executable),
                arguments={
                    "customer_id": str(customer.customer_id),
                    "warehouse_id": str(warehouse_id),
                    "delivery_address": customer.address,
                },
                depends_on_order=True,
            )
        )

    return calls
