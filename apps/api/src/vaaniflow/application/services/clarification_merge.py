"""
Slot-targeted merging of a clarification reply into the open request (ADR-023).

A clarification asks for specific slots (customer, product, quantity). A reply
such as "Sharma Builders" or "200 bag" is compiled with the normal UNDERSTAND
compiler and merged **only** into those slots of the original SemanticState;
everything else that was already understood is kept. The merged state is then
re-evaluated and goes through the same ACT pipeline (context, validation,
policy, approval) as any request — a clarification never executes anything.

Outcomes:
* ``merged`` — a new transcript (original text + reply) and SemanticState whose
  spans stay inside that transcript.
* ``instruction`` — the reply is a complete instruction (it names actions), so
  it is processed as a new instruction on the run, as before.
* ``refused`` — the reply answers nothing that was asked, or contradicts a fact
  that was already understood; nothing changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from vaaniflow.domain.models.followup import ClarificationRecord
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import (
    SemanticEntity,
    SemanticEntityType,
    SemanticItem,
    SemanticQuantity,
    SemanticSlot,
    SemanticState,
    TextSpan,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic import SemanticCompiler

MERGEABLE_SLOTS = (SemanticSlot.CUSTOMER, SemanticSlot.PRODUCT, SemanticSlot.QUANTITY)
_MAX_BARE_ANSWER = 80  # characters; a longer bare reply is not a slot answer
# Words a reply may contain besides its answer ("200 bag hi", "Sharma Builders ko").
_FILLER = frozenset(
    {
        "ko",
        "ka",
        "ki",
        "ke",
        "hai",
        "hain",
        "ji",
        "sirf",
        "bas",
        "only",
        "just",
        "the",
        "for",
        "to",
        "please",
        "wala",
        "wale",
        "waala",
        "yes",
        "haan",
        "hi",
        "bhai",
    }
)
# An explicit answer from the user to the slot they were asked about.
_ANSWER_CONFIDENCE = Confidence(score=0.75, source=ConfidenceSource.HUMAN)


@dataclass
class MergeOutcome:
    kind: Literal["merged", "instruction", "refused"]
    message: str = ""
    transcript: Transcript | None = None
    semantic_state: SemanticState | None = None
    filled_slots: list[SemanticSlot] = field(default_factory=list)


def requested_slots(clarification: ClarificationRecord) -> list[SemanticSlot]:
    """Which mergeable slots the clarification is waiting for, from its evidence."""
    wanted: set[SemanticSlot] = set()
    for item in clarification.unresolved:
        slot = str(item.get("slot") or "").upper()
        code = str(item.get("code") or "").upper()
        if slot == "CUSTOMER" or code in {"MISSING_CUSTOMER", "CUSTOMER_IDENTITY"}:
            wanted.add(SemanticSlot.CUSTOMER)
        elif slot.startswith("PRODUCT") or code in {"MISSING_PRODUCT", "PRODUCT_IDENTITY"}:
            wanted.add(SemanticSlot.PRODUCT)
        elif slot in {"QUANTITY", "ITEMS[0].QUANTITY"} or code == "MISSING_QUANTITY":
            wanted.add(SemanticSlot.QUANTITY)
    return [slot for slot in MERGEABLE_SLOTS if slot in wanted]


def merge_clarification(
    clarification: ClarificationRecord,
    reply: str,
    *,
    compiler: SemanticCompiler,
    now: datetime,
) -> MergeOutcome:
    original = clarification.understand_result
    base = original.semantic_state
    reply = reply.strip()
    if not reply:
        return MergeOutcome("refused", "The reply was empty; nothing was changed.")

    reply_transcript = Transcript(
        transcript_id=uuid4(),
        provider="clarification",
        language=original.transcript.language,
        text=reply,
        created_at=now,
    )
    answer = compiler.compile(reply_transcript, run_id=base.run_id)
    if answer.requested_actions or answer.negated_actions:
        return MergeOutcome("instruction")

    wanted = requested_slots(clarification)
    if not wanted or len(base.items) > 1:
        return MergeOutcome(
            "refused",
            "This request cannot be completed from a short reply. "
            "Send the complete corrected instruction.",
        )

    offset = len(original.transcript.text) + 1  # the reply follows a newline
    merged_text = f"{original.transcript.text}\n{reply}"

    def shifted(span: TextSpan) -> TextSpan:
        return TextSpan(start=span.start + offset, end=span.end + offset)

    def entity(source: SemanticEntity, entity_type: SemanticEntityType) -> SemanticEntity:
        return SemanticEntity(
            entity_id=uuid4(),
            entity_type=entity_type,
            surface_text=source.surface_text,
            normalized_text=source.normalized_text,
            span=shifted(source.span),
            confidence=source.confidence,
        )

    def bare(entity_type: SemanticEntityType) -> SemanticEntity:
        return SemanticEntity(
            entity_id=uuid4(),
            entity_type=entity_type,
            surface_text=reply,
            normalized_text=reply.lower(),
            span=TextSpan(start=offset, end=offset + len(reply)),
            confidence=_ANSWER_CONFIDENCE,
        )

    answer_item = answer.items[0] if len(answer.items) == 1 else None
    answer_quantity = answer_item.quantity if answer_item else None
    answered: dict[SemanticSlot, Any] = {}
    if answer.customer is not None:
        answered[SemanticSlot.CUSTOMER] = entity(answer.customer, SemanticEntityType.CUSTOMER)
    if answer_item is not None and answer_item.product is not None:
        answered[SemanticSlot.PRODUCT] = entity(answer_item.product, SemanticEntityType.PRODUCT)
    if answer_quantity is not None:
        answered[SemanticSlot.QUANTITY] = SemanticQuantity(
            value=answer_quantity.value,
            unit=answer_quantity.unit,
            surface_text=answer_quantity.surface_text,
            span=shifted(answer_quantity.span),
            confidence=answer_quantity.confidence,
        )
    # A bare answer ("Sharma Builders", "UltraTech") fills the one name slot asked about.
    names_asked = [s for s in wanted if s in (SemanticSlot.CUSTOMER, SemanticSlot.PRODUCT)]
    if (
        not answered
        and len(wanted) == 1
        and len(names_asked) == 1
        and len(reply) <= _MAX_BARE_ANSWER
        and not answer.items
        and not answer.pricing
    ):
        entity_type = (
            SemanticEntityType.CUSTOMER
            if names_asked[0] is SemanticSlot.CUSTOMER
            else SemanticEntityType.PRODUCT
        )
        answered[names_asked[0]] = bare(entity_type)

    base_item = base.items[0] if base.items else None
    known: dict[SemanticSlot, str | None] = {
        SemanticSlot.CUSTOMER: base.customer.normalized_text if base.customer else None,
        SemanticSlot.PRODUCT: base_item.product.normalized_text
        if base_item and base_item.product
        else None,
        SemanticSlot.QUANTITY: f"{base_item.quantity.value} {base_item.quantity.unit}"
        if base_item and base_item.quantity
        else None,
    }
    for slot, value in answered.items():
        if slot in wanted:
            continue
        given = (
            f"{value.value} {value.unit}"
            if isinstance(value, SemanticQuantity)
            else value.normalized_text
        )
        if known[slot] is not None and known[slot] != given:
            return MergeOutcome(
                "refused",
                f"The reply changes {slot.value.lower()}, which was not asked about. "
                "Nothing was changed; send the complete corrected instruction instead.",
            )
    filled = [slot for slot in wanted if slot in answered]
    if filled and _has_unexplained_words(reply, answered.values(), offset):
        return MergeOutcome(
            "refused",
            "The reply contains more than the answer that was asked for. Nothing was changed; "
            "reply with just the missing value or send the complete corrected instruction.",
        )
    if not filled:
        asked = ", ".join(s.value.lower() for s in wanted)
        return MergeOutcome(
            "refused", f"The reply did not answer what was asked ({asked}). Nothing was changed."
        )
    if answer.pricing or answer.references or answer.temporal_expressions:
        return MergeOutcome(
            "refused",
            "The reply adds a price or date. Send the complete corrected instruction instead.",
        )

    customer = answered.get(SemanticSlot.CUSTOMER, base.customer)
    items = list(base.items)
    if SemanticSlot.PRODUCT in filled or SemanticSlot.QUANTITY in filled:
        item = items[0] if items else None
        merged_item = SemanticItem(
            item_id=item.item_id if item else uuid4(),
            product=answered.get(SemanticSlot.PRODUCT, item.product if item else None),
            quantity=answered.get(SemanticSlot.QUANTITY, item.quantity if item else None),
        )
        items = [merged_item]
    merged_transcript = Transcript(
        transcript_id=uuid4(),
        provider=original.transcript.provider,
        language=original.transcript.language,
        text=merged_text,
        created_at=now,
    )
    data = base.model_dump()
    data.update(
        semantic_state_id=uuid4(),
        version=base.version + 1,
        source_transcript_id=merged_transcript.transcript_id,
        customer=customer.model_dump() if customer else None,
        items=[i.model_dump() for i in items],
        # Ambiguities about the slots just answered are resolved; others remain.
        ambiguities=[a.model_dump() for a in base.ambiguities if a.slot not in filled],
        created_at=now,
    )
    state = SemanticState.model_validate(data)
    return MergeOutcome(
        "merged", transcript=merged_transcript, semantic_state=state, filled_slots=filled
    )


def _has_unexplained_words(reply: str, answers: Any, offset: int) -> bool:
    """True if the reply has words outside the answered spans (other than filler)."""
    leftover = list(reply)
    for value in answers:
        start, end = value.span.start - offset, value.span.end - offset
        for i in range(max(start, 0), min(end, len(reply))):
            leftover[i] = " "
    words = re.findall(r"[^\W_]+", "".join(leftover).lower())
    return any(word not in _FILLER for word in words)
