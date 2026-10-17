"""
Requested-action, intent and urgency extraction.

Actions are detected per sentence so that "...dispatch karo. Invoice bana ke
... bhej do." yields DISPATCH for the first sentence and invoice/approval/
notification for the second, instead of a single keyword winning globally.
The primary intent is derived from the most consequential action.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from vaaniflow.domain.schemas.semantic import (
    ActionParty,
    IntentType,
    RequestedAction,
    RequestedActionType,
    TextSpan,
    Urgency,
)
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.lexicon import URGENCY_CRITICAL, URGENCY_HIGH
from vaaniflow.semantic.text import Token, find_phrases

_DISPATCH_VERBS = frozenset({"dispatch", "ship", "deliver", "delivery"})
_SEND_VERBS = frozenset({"send", "bhej", "bhejo", "bhejna", "bhejdo", "bhijwa", "bhijwao"})
_DOCUMENT_NOUNS = frozenset(
    {
        "invoice",
        "bill",
        "billing",
        "quote",
        "quotation",
        "message",
        "details",
        "photo",
        "pdf",
        "copy",
        "receipt",
        "approval",
        "approve",
    }
)
_INVOICE_NOUNS = frozenset({"invoice", "bill", "billing"})
_APPROVAL_WORDS = frozenset({"approve", "approval", "manzoori"})
_CHANNELS = {"whatsapp": "WHATSAPP", "sms": "SMS", "email": "EMAIL", "mail": "EMAIL"}
_NOTIFY_WORDS = frozenset({"notify", "notification", "inform", "message"})
_SPEAKER_WORDS = frozenset({"mujhe", "mere", "mera", "my", "humein", "hume"})
_CUSTOMER_WORDS = frozenset({"customer", "party", "client"})
_CANCEL_WORDS = frozenset({"cancel", "radd"})
_UPDATE_WORDS = frozenset({"update", "modify", "change", "badal", "badlo", "badalna"})
_ORDER_CREATE_WORDS = frozenset(
    {"place", "create", "book", "bana", "banao", "lo", "le", "lena", "likho", "new"}
)
_INVENTORY_WORDS = frozenset({"stock", "inventory", "availability"})
_PRICE_WORDS = frozenset({"rate", "price", "cost", "bhav"})
_QUESTION_WORDS = frozenset(
    {"kya", "what", "how", "kitna", "kitne", "kitni", "batao", "bataiye", "bata", "tell", "?"}
)
_PRICE_SETTING_WORDS = frozenset({"lagana", "lagao", "laga", "apply", "use", "at"})

_INTENT_PRIORITY: tuple[tuple[RequestedActionType, IntentType], ...] = (
    (RequestedActionType.CANCEL_ORDER, IntentType.CANCEL_ORDER),
    (RequestedActionType.UPDATE_ORDER, IntentType.UPDATE_ORDER),
    (RequestedActionType.DISPATCH, IntentType.CREATE_DISPATCH_ORDER),
    (RequestedActionType.CREATE_ORDER, IntentType.CREATE_ORDER),
    (RequestedActionType.CREATE_INVOICE_DRAFT, IntentType.CREATE_INVOICE),
    (RequestedActionType.CHECK_INVENTORY, IntentType.CHECK_INVENTORY),
    (RequestedActionType.CHECK_PRICE, IntentType.CHECK_PRICE),
    (RequestedActionType.SEND_NOTIFICATION, IntentType.SEND_NOTIFICATION),
)

_MODIFYING = frozenset({RequestedActionType.CANCEL_ORDER, RequestedActionType.UPDATE_ORDER})
_CREATING = frozenset({RequestedActionType.DISPATCH, RequestedActionType.CREATE_ORDER})


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: IntentType
    confidence: float
    conflicting: tuple[RequestedActionType, ...] = ()


def _sentences(tokens: Sequence[Token]) -> list[list[Token]]:
    grouped: dict[int, list[Token]] = {}
    for token in tokens:
        grouped.setdefault(token.sentence, []).append(token)
    return list(grouped.values())


def _first(sentence: Sequence[Token], words: frozenset[str]) -> Token | None:
    return next((token for token in sentence if token.lower in words), None)


def extract_requested_actions(
    text: str,
    tokens: Sequence[Token],
    *,
    goods_tokens: set[int],
    customer_tokens: set[int],
    correction_tokens: set[int],
) -> list[RequestedAction]:
    """
    goods_tokens: token indexes of product/quantity mentions.
    customer_tokens: token indexes of customer mentions.
    correction_tokens: token indexes of correction markers ("change that to").
    """
    actions: dict[RequestedActionType, RequestedAction] = {}

    def add(
        action_type: RequestedActionType,
        cue: Token,
        score: float,
        *,
        recipient: ActionParty | None = None,
        channel: str | None = None,
    ) -> None:
        existing = actions.get(action_type)
        if existing is not None and existing.confidence.score >= score:
            return
        actions[action_type] = RequestedAction(
            action_id=uuid4(),
            action_type=action_type,
            explicit=True,
            recipient=recipient,
            channel=channel,
            surface_text=text[cue.start : cue.end],
            span=TextSpan(start=cue.start, end=cue.end),
            confidence=conf.rule(score),
        )

    for sentence in _sentences(tokens):
        words = {token.lower for token in sentence}
        indexes = {token.index for token in sentence}
        has_goods = bool(indexes & goods_tokens)
        has_documents = bool(words & _DOCUMENT_NOUNS)
        speaker = bool(words & _SPEAKER_WORDS)
        customer = bool(words & _CUSTOMER_WORDS) or bool(indexes & customer_tokens)

        if cue := _first(sentence, _DISPATCH_VERBS):
            add(RequestedActionType.DISPATCH, cue, conf.ACTION_EXPLICIT)
        elif (cue := _first(sentence, _SEND_VERBS)) and has_goods and not has_documents:
            add(RequestedActionType.DISPATCH, cue, conf.ACTION_GENERIC_VERB)

        if cue := _first(sentence, _INVOICE_NOUNS):
            add(RequestedActionType.CREATE_INVOICE_DRAFT, cue, conf.ACTION_EXPLICIT)

        if cue := _first(sentence, _APPROVAL_WORDS):
            add(
                RequestedActionType.REQUEST_APPROVAL,
                cue,
                conf.ACTION_EXPLICIT,
                recipient=ActionParty.SPEAKER if speaker else ActionParty.UNSPECIFIED,
            )

        channel_token = next((t for t in sentence if t.lower in _CHANNELS), None)
        notify_token = _first(sentence, _NOTIFY_WORDS)
        if cue := (channel_token or notify_token):
            recipient = (
                ActionParty.SPEAKER
                if speaker
                else ActionParty.CUSTOMER
                if customer
                else ActionParty.UNSPECIFIED
            )
            add(
                RequestedActionType.SEND_NOTIFICATION,
                cue,
                conf.ACTION_EXPLICIT,
                recipient=recipient,
                channel=_CHANNELS[channel_token.lower] if channel_token else None,
            )

        if cue := _first(sentence, _CANCEL_WORDS):
            add(RequestedActionType.CANCEL_ORDER, cue, conf.ACTION_EXPLICIT)

        update_cue = next(
            (t for t in sentence if t.lower in _UPDATE_WORDS and t.index not in correction_tokens),
            None,
        )
        if update_cue is not None and "order" in words:
            add(RequestedActionType.UPDATE_ORDER, update_cue, conf.ACTION_EXPLICIT)

        order_cue = _first(sentence, frozenset({"order"}))
        if (
            order_cue is not None
            and not words & _CANCEL_WORDS
            and update_cue is None
            and (words & _ORDER_CREATE_WORDS or has_goods)
        ):
            score = (
                conf.ACTION_EXPLICIT if words & _ORDER_CREATE_WORDS else conf.ACTION_GENERIC_VERB
            )
            add(RequestedActionType.CREATE_ORDER, order_cue, score)

        if cue := _first(sentence, _INVENTORY_WORDS):
            add(RequestedActionType.CHECK_INVENTORY, cue, conf.ACTION_EXPLICIT)

        price_cue = _first(sentence, _PRICE_WORDS)
        if price_cue is not None and words & _QUESTION_WORDS and not words & _PRICE_SETTING_WORDS:
            add(RequestedActionType.CHECK_PRICE, price_cue, conf.ACTION_EXPLICIT)

    return sorted(actions.values(), key=lambda action: action.span.start)


def decide_intent(actions: Sequence[RequestedAction]) -> IntentDecision:
    present = {action.action_type: action for action in actions}

    if not present:
        return IntentDecision(IntentType.UNKNOWN, conf.INTENT_NONE)

    modifying = [kind for kind in present if kind in _MODIFYING]
    creating = [kind for kind in present if kind in _CREATING]

    for action_type, intent in _INTENT_PRIORITY:
        if action_type in present:
            if modifying and creating:
                return IntentDecision(
                    intent,
                    conf.INTENT_CONFLICT,
                    conflicting=tuple(sorted({*modifying, *creating})),
                )
            return IntentDecision(intent, present[action_type].confidence.score)

    return IntentDecision(IntentType.UNKNOWN, conf.INTENT_NONE)  # pragma: no cover


def extract_urgency(tokens: Sequence[Token]) -> Urgency:
    if find_phrases(tokens, URGENCY_CRITICAL):
        return Urgency.CRITICAL
    if find_phrases(tokens, URGENCY_HIGH):
        return Urgency.HIGH
    return Urgency.NORMAL
