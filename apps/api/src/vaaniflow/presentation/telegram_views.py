"""
Telegram message rendering (Phase 3): a projection of actual VaaniFlow state.

Every value shown comes from the WorkflowResult, the evaluation result or the
repositories passed in; nothing is a demo constant. Every dynamic value is
HTML-escaped for Telegram's HTML parse mode. Headers follow the backend status
and per-step evidence (``StepStatus``), never the fact that a call returned.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from vaaniflow.application.services.orchestrator import WorkflowResult
from vaaniflow.domain.models.principal import Principal
from vaaniflow.domain.models.validation import ValidationStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.evaluation.models import SuiteEvaluationResult
from vaaniflow.execution.plan import StepOutcome, StepStatus
from vaaniflow.presentation.telegram_security import (
    approve_data,
    clarify_data,
    confirm_data,
    reject_data,
)

Markup = dict[str, Any] | None
_MAX_FIELD = 300
_MAX_LINES = 12

_TOOL_LABELS = {
    "create_order": "Order",
    "create_invoice_draft": "Invoice draft",
    "dispatch_order": "Dispatch",
}
_STEP_MARKS = {
    StepStatus.VERIFIED: ("✓", "VERIFIED"),
    StepStatus.FAILED: ("✗", "FAILED"),
    StepStatus.UNKNOWN: ("?", "UNKNOWN"),
    StepStatus.NOT_ATTEMPTED: ("–", "NOT ATTEMPTED"),
}
_CHECK_MARKS = {
    ValidationStatus.PASSED: "✓",
    ValidationStatus.WARNING: "⚠",
    ValidationStatus.FAILED: "✗",
}


def esc(value: object, limit: int = _MAX_FIELD) -> str:
    """Escape for Telegram HTML; long values are shortened before escaping."""
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=False)


def money(amount: Decimal | float | str | None, currency: str | None = "INR") -> str:
    """₹ with Indian digit grouping for INR (1,07,520.00); plain otherwise."""
    if amount is None:
        return "—"
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    if currency not in (None, "INR"):
        return f"{esc(currency)} {value:,.2f}"
    sign = "-" if value < 0 else ""
    whole, _, fraction = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}₹{whole}.{fraction}"


def short(value: object) -> str:
    """The last 8 characters of an id (distinct even for the synthetic sequential ids)."""
    return esc(str(value)[-8:])


def _bullets(lines: Iterable[str]) -> list[str]:
    rendered = list(lines)
    if len(rendered) > _MAX_LINES:
        rendered = [*rendered[:_MAX_LINES], f"… and {len(rendered) - _MAX_LINES} more"]
    return [f"• {line}" for line in rendered]


def _section(title: str, lines: Sequence[str]) -> list[str]:
    return [f"\n<b>{title}</b>", *lines] if lines else []


# --------------------------------------------------------------------------- #
# What was understood and what the business records say
# --------------------------------------------------------------------------- #


def _understood(result: WorkflowResult) -> list[str]:
    if result.understand_result is None:
        return []
    state = result.understand_result.semantic_state
    lines = [f"Intent: <code>{esc(state.intent.value)}</code>"]
    if state.customer:
        lines.append(f"Customer (as said): {esc(state.customer.surface_text)}")
    for item in state.items:
        product = esc(item.product.surface_text) if item.product else "<i>not stated</i>"
        quantity = (
            f"{esc(item.quantity.value)} {esc(item.quantity.unit or '')}".strip()
            if item.quantity
            else "<i>quantity not stated</i>"
        )
        lines.append(f"Item: {product} — {quantity}")
    for price in state.pricing:
        claim = money(price.amount, price.currency or "INR") if price.amount else "a past rate"
        unit = f"/{esc(price.per_unit)}" if price.per_unit else ""
        lines.append(f"Price said: {claim}{unit} <i>({esc(price.source.value.lower())})</i>")
    if state.tax:
        lines.append(
            f"Tax said: {esc(state.tax.tax_type)} {esc(state.tax.treatment.value.lower())}"
        )
    for expression in state.temporal_expressions:
        lines.append(
            f"Time reference: “{esc(expression.surface_text)}” = "
            f"<code>{esc(expression.normalized_expression)}</code>"
        )
    if state.requested_actions:
        actions = ", ".join(esc(a.action_type.value) for a in state.requested_actions)
        lines.append(f"Requested: {actions}")
    if state.negated_actions:
        negated = ", ".join(esc(a.action_type.value) for a in state.negated_actions)
        lines.append(f"Told NOT to: {negated}")
    if state.urgency.value != "NORMAL":
        lines.append(f"Urgency: {esc(state.urgency.value)}")
    return _bullets(lines)


def _business(result: WorkflowResult) -> list[str]:
    context = result.business_context
    if context is None:
        return []
    lines: list[str] = []
    if context.customer:
        customer = context.customer.customer
        lines.append(f"Customer: {esc(customer.name)} <code>{short(customer.customer_id)}</code>")
    for resolved in context.products:
        product = resolved.product
        lines.append(f"Product: {esc(product.name)} <code>{esc(product.sku)}</code>")
    for resolved_quote in context.quotes:
        quote = resolved_quote.quote
        validity = f", valid until {esc(quote.valid_until)}" if quote.valid_until else ""
        lines.append(
            f"Quote: {money(quote.unit_price, quote.currency)}/{esc(quote.unit)} given "
            f"{esc(quote.quoted_on)}{validity} — {esc(quote.status.value)}"
        )
    if context.resolved_price:
        price = context.resolved_price
        source = (
            f" from quote <code>{short(price.source_quote_id)}</code>"
            if price.source_quote_id
            else ""
        )
        lines.append(
            f"Price used: {money(price.unit_price, price.currency)}/{esc(price.unit)}{source}"
        )
    for resolved_inventory in context.inventory:
        stock = resolved_inventory.inventory
        net = stock.available_quantity - stock.reserved_quantity
        lines.append(
            f"Stock: {esc(net)} free ({esc(stock.available_quantity)} available, "
            f"{esc(stock.reserved_quantity)} reserved) at <code>{short(stock.warehouse_id)}</code>"
        )
    tax = result.tax_calculation
    if tax:
        components = " + ".join(
            f"{esc(c.name)} {esc((c.rate * 100).normalize())}% {money(c.amount)}"
            for c in tax.components
        )
        lines.append(f"Tax ({esc(tax.rule_version)}): {components or money(tax.total_tax)}")
        lines.append(
            f"Total: {money(tax.taxable_amount)} + {money(tax.total_tax)} = "
            f"<b>{money(tax.total_amount)}</b>"
        )
    for error in context.resolution_errors:
        lines.append(f"⚠ {esc(error)}")
    return _bullets(lines)


def _validation(result: WorkflowResult) -> list[str]:
    validation = result.validation_result
    if validation is None or not validation.checks:
        return []
    passed = sum(1 for c in validation.checks if c.status is ValidationStatus.PASSED)
    lines = [f"{passed}/{len(validation.checks)} checks passed ({esc(validation.status.value)})"]
    lines += [
        f"{_CHECK_MARKS.get(c.status, '•')} {esc(c.check_type)}: {esc(c.message)}"
        for c in validation.checks
    ]
    if result.risk_assessment:
        risk = result.risk_assessment
        lines.append(f"Risk: {esc(risk.level.value)} ({risk.score:.2f})")
    return _bullets(lines)


def _plan(result: WorkflowResult) -> list[str]:
    plan = result.plan
    if plan is None:
        return []
    lines = [
        f"{n}. <code>{esc(call.tool_name)}</code> "
        f"({', '.join(esc(a.value) for a in call.action_types)})"
        for n, call in enumerate(plan.tool_calls, start=1)
    ]
    lines += [f"→ {esc(a.value)}: read only" for a in plan.read_actions]
    lines += [
        f"→ {esc(a.value)}: not supported in this prototype; will be handed to an operator"
        for a in plan.unsupported_actions
    ]
    lines += [
        f"✗ {esc(a.value)}: excluded (you said not to)" for a in plan.excluded_negated_actions
    ]
    return lines


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #


def render_workflow(result: WorkflowResult, transcript: str) -> tuple[str, Markup]:
    """The card for any non-execution result, chosen by the backend status."""
    status = result.run.status
    if status is VoiceRunStatus.APPROVAL_REQUIRED and result.approval:
        return render_approval(result, transcript)
    if status is VoiceRunStatus.CONFIRMATION_REQUIRED and result.confirmation:
        return render_confirmation(result, transcript)
    if status is VoiceRunStatus.CLARIFICATION_REQUIRED and result.clarification:
        return render_clarification(result, transcript), None
    if result.step_outcomes:
        return render_receipt(result, approver=None), None
    return render_outcome(result, transcript), None


def _header(title: str, result: WorkflowResult) -> list[str]:
    return [
        f"<b>{title}</b>",
        f"<code>Run {short(result.run.run_id)} · {esc(result.run.status.value)}</code>",
    ]


def _instruction(transcript: str) -> list[str]:
    return [f"\n<b>Instruction</b>\n<i>{esc(transcript, 500)}</i>"] if transcript else []


def render_approval(result: WorkflowResult, transcript: str) -> tuple[str, Markup]:
    assert result.approval is not None
    lines = _header("⚡ Approval required — nothing has been executed", result)
    lines += _instruction(transcript)
    lines += _section("Understood", _understood(result))
    lines += _section("Business records", _business(result))
    lines += _section("Validation", _validation(result))
    lines += _section("Planned operations (in order)", _plan(result))
    if result.decision:
        lines += _section("Why approval", [esc(result.decision.reason)])
    total = result.tax_calculation.total_amount if result.tax_calculation else None
    approve_label = f"✅ Approve ({money(total)})" if total is not None else "✅ Approve"
    run_id, approval_id = result.run.run_id, result.approval.approval_id
    markup = {
        "inline_keyboard": [
            [{"text": approve_label, "callback_data": approve_data(run_id, approval_id)}],
            [
                {"text": "❓ Clarify", "callback_data": clarify_data(run_id)},
                {"text": "❌ Reject", "callback_data": reject_data(run_id, approval_id)},
            ],
        ]
    }
    return "\n".join(lines), markup


def render_confirmation(result: WorkflowResult, transcript: str) -> tuple[str, Markup]:
    assert result.confirmation is not None
    lines = _header("❔ Please confirm — nothing has been executed", result)
    lines += _instruction(transcript)
    lines += _section("Asking because", _bullets(esc(w) for w in result.confirmation.warnings))
    lines += _section("Understood", _understood(result))
    lines.append("\n<i>Yes continues to an approval request; it does not execute anything.</i>")
    run_id = result.run.run_id
    markup = {
        "inline_keyboard": [
            [
                {"text": "Yes", "callback_data": confirm_data(run_id, "yes")},
                {"text": "No", "callback_data": confirm_data(run_id, "no")},
            ]
        ]
    }
    return "\n".join(lines), markup


def render_clarification(result: WorkflowResult, transcript: str) -> str:
    clarification = result.clarification
    assert clarification is not None
    lines = _header("❓ Clarification needed — nothing has been executed", result)
    lines += _instruction(transcript)
    lines.append(f"\n{esc(clarification.reason, 500)}")
    missing = []
    for item in clarification.unresolved:
        text = esc(item.get("message", item))
        candidates = item.get("candidates")
        if candidates:
            text += f" (options: {', '.join(esc(c) for c in candidates)})"
        missing.append(text)
    lines += _section("Missing or unclear", _bullets(missing))
    lines += _section("Understood so far", _understood(result))
    lines.append(
        "\n<i>Reply with just the missing value (for example the customer name or "
        "the quantity), or send the complete corrected instruction.</i>"
    )
    if result.message and result.message != clarification.reason:
        lines.append(f"\n{esc(result.message, 500)}")
    return "\n".join(lines)


def render_outcome(result: WorkflowResult, transcript: str) -> str:
    """A result without executed steps (blocked, handed off, failed, read-only)."""
    status = result.run.status
    titles = {
        VoiceRunStatus.HANDOFF: "🛑 Handed to a human operator — nothing was executed",
        VoiceRunStatus.BLOCKED: "⛔ Blocked — nothing was executed",
        VoiceRunStatus.FAILED: "❌ Not executed",
        VoiceRunStatus.COMPLETED: "ℹ️ Done",
    }
    lines = _header(titles.get(status, f"ℹ️ {esc(status.value)}"), result)
    lines += _instruction(transcript)
    lines.append(f"\n{esc(result.message, 800)}")
    if result.handoff_case:
        lines.append(
            f"\nHandoff case <code>{short(result.handoff_case.handoff_id)}</code> is open."
        )
    return "\n".join(lines)


def _step_line(step: StepOutcome) -> str:
    mark, label = _STEP_MARKS.get(step.status, ("•", step.status.value))
    name = _TOOL_LABELS.get(step.tool_name, step.tool_name)
    record = f" <code>{short(step.entity_id)}</code>" if step.entity_id else ""
    return f"{mark} {esc(name)}{record} — <b>{label}</b>: {esc(step.message)}"


def render_receipt(result: WorkflowResult, approver: Principal | None) -> str:
    """Execution receipt from per-step evidence; the header follows the backend status."""
    steps = result.step_outcomes
    statuses = {s.status for s in steps}
    unsupported = result.plan.unsupported_actions if result.plan else []
    if StepStatus.UNKNOWN in statuses:
        title = "❓ Execution outcome unknown"
    elif result.run.status is VoiceRunStatus.COMPLETED and statuses == {StepStatus.VERIFIED}:
        title = "✅ Execution complete — every step verified"
    elif result.run.status is VoiceRunStatus.PARTIALLY_COMPLETED:
        title = "⚠️ Execution partially completed"
    elif (
        result.run.status is VoiceRunStatus.HANDOFF and steps and statuses == {StepStatus.VERIFIED}
    ):
        title = "↪️ Execution completed with handoff"
    elif steps and StepStatus.VERIFIED not in statuses:
        title = "❌ Execution failed — nothing was verified"
    else:
        title = f"ℹ️ Execution finished: {esc(result.run.status.value)}"
    lines = _header(title, result)
    if approver is not None:
        roles = ", ".join(r.value for r in approver.roles)
        lines.append(
            f"<b>Authorized by:</b> {esc(approver.display_name)} [{esc(roles)}] via "
            f"{esc(approver.authentication_method)}"
        )
    lines += _section("Steps", [_step_line(step) for step in steps])
    handoff = [
        f"→ {esc(action.value)}: not supported in this prototype — not performed"
        for action in unsupported
    ]
    if StepStatus.UNKNOWN in statuses:
        handoff.append("No automatic retry was performed. Operator verification required.")
    if result.handoff_case:
        handoff.append(
            f"Handoff case <code>{short(result.handoff_case.handoff_id)}</code> is open."
        )
    lines += _section("Handoff", handoff)
    lines += _section("Details", [esc(result.message, 800)])
    return "\n".join(lines)


def render_rejection(run_id: object, rejecter: Principal) -> str:
    return (
        f"❌ <b>Execution plan rejected</b>\n<code>Run {short(run_id)}</code>\n"
        f"<i>Rejected by {esc(rejecter.display_name)}. Nothing was executed.</i>"
    )


# --------------------------------------------------------------------------- #
# Benchmark and status
# --------------------------------------------------------------------------- #


def render_benchmark(suite: SuiteEvaluationResult) -> str:
    lines = [
        "📊 <b>Evaluation suite</b> (sandbox: isolated synthetic data)",
        (
            f"• Scenarios: <b>{suite.passed_scenarios}/{suite.total_scenarios} passed</b>, "
            f"{suite.failed_scenarios} failed"
        ),
        f"• Safety violations: <b>{suite.safety_violations}</b>",
        f"• False execution rate: {suite.false_execution_rate:.1%}",
        f"• False confirmation rate: {suite.false_confirmation_rate:.1%}",
        "",
    ]
    for r in suite.results:
        mark = "✓" if r.passed else "✗"
        lines.append(
            f"{mark} <code>{esc(r.scenario_id.value)}</code>: "
            f"{esc(r.actual_decision)} / {esc(r.actual_status)}"
        )
        if not r.passed:
            lines.append(f"   <i>{esc(r.details, 200)}</i>")
    return "\n".join(lines)


def render_status(facts: dict[str, Any]) -> str:
    lines = ["ℹ️ <b>VaaniFlow status</b> (this process, in-memory state)"]
    lines += [f"• {esc(key)}: <b>{esc(value)}</b>" for key, value in facts.items()]
    return "\n".join(lines)
