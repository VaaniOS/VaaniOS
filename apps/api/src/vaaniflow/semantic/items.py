"""
Binding of quantity mentions to product mentions into line items.

"200 bags of UltraTech cement and 50 kg of steel rods" yields two items,
each with its own product and quantity, so downstream never has to guess
which quantity belongs to which product.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.text import Token

_LINKERS = frozenset({"of", "ka", "ki", "ke", "wala", "wali"})


@dataclass(slots=True)
class ItemDraft:
    product: Mention | None
    quantity: Mention | None
    conflicting_quantities: list[Mention] = field(default_factory=list)
    item_id: UUID = field(default_factory=uuid4)

    @property
    def start(self) -> int:
        positions = [m.start for m in (self.product, self.quantity) if m is not None]
        return min(positions)

    @property
    def end(self) -> int:
        positions = [m.end for m in (self.product, self.quantity) if m is not None]
        return max(positions)

    @property
    def unit(self) -> str | None:
        return self.quantity.unit if self.quantity is not None else None


def _final(mention: Mention, replacements: Mapping[UUID, Mention]) -> Mention:
    while mention.mention_id in replacements:
        mention = replacements[mention.mention_id]
    return mention


def _adjacent_after(tokens: Sequence[Token], quantity: Mention, product: Mention) -> bool:
    if product.start < quantity.end or product.start - quantity.end > 1:
        return False
    gap = tokens[quantity.end : product.start]
    return all(token.lower in _LINKERS for token in gap)


def _adjacent_before(tokens: Sequence[Token], quantity: Mention, product: Mention) -> bool:
    if product.end > quantity.start or quantity.start - product.end > 1:
        return False
    gap = tokens[product.end : quantity.start]
    return all(token.lower in _LINKERS or token.text == "," for token in gap)


def bind_items(
    tokens: Sequence[Token],
    quantities: Sequence[Mention],
    products: Sequence[Mention],
    replacements: Mapping[UUID, Mention],
) -> list[ItemDraft]:
    """
    quantities/products include superseded mentions; ``replacements`` maps a
    superseded mention to the mention that corrected it. Adjacency is judged
    on every mention, then each side is mapped to its final value, so
    "200 bags UltraTech cement, sorry, ACC cement" binds 200 bags to ACC.
    """
    pairs: list[tuple[Mention, Mention]] = []
    used_quantities: set[UUID] = set()
    used_products: set[UUID] = set()

    for quantity in sorted(quantities, key=lambda m: m.start):
        partner = next(
            (p for p in products if _adjacent_after(tokens, quantity, p)),
            None,
        )
        if partner is None and quantity.kind is MentionKind.QUANTITY:
            partner = next(
                (p for p in products if _adjacent_before(tokens, quantity, p)),
                None,
            )
        if partner is None:
            continue

        # A bare number bound to a product ("200 UltraTech cement") stays a
        # unitless quantity; Input Evaluation asks for the unit.
        final_quantity = _final(quantity, replacements)
        final_product = _final(partner, replacements)
        pairs.append((final_quantity, final_product))
        used_quantities.add(final_quantity.mention_id)
        used_products.add(final_product.mention_id)

    # Unbound bare numbers are not quantities (they may be order numbers,
    # specs, ...); only number+unit mentions survive on their own.
    finals_q: dict[UUID, Mention] = {}
    for quantity in quantities:
        final_quantity = _final(quantity, replacements)
        if final_quantity.kind is MentionKind.QUANTITY:
            finals_q[final_quantity.mention_id] = final_quantity
    finals_p = {_final(p, replacements).mention_id: _final(p, replacements) for p in products}

    loose_quantities = [m for i, m in finals_q.items() if i not in used_quantities]
    loose_products = [m for i, m in finals_p.items() if i not in used_products]

    # A single unbound quantity and a single unbound product in one request
    # describe the same line ("UltraTech cement bhejo Sharma ko, 200 bags").
    if len(loose_quantities) == 1 and len(loose_products) == 1:
        pairs.append((loose_quantities[0], loose_products[0]))
        loose_quantities, loose_products = [], []

    drafts: list[ItemDraft] = []
    by_product: dict[str, ItemDraft] = {}

    for quantity, product in pairs:
        draft = by_product.get(product.normalized)
        if draft is None:
            draft = ItemDraft(product=product, quantity=quantity)
            by_product[product.normalized] = draft
            drafts.append(draft)
            continue
        if draft.quantity is not None and (
            draft.quantity.mention_id == quantity.mention_id
            or (draft.quantity.value, draft.quantity.unit) == (quantity.value, quantity.unit)
        ):
            continue
        if draft.quantity is not None:
            draft.conflicting_quantities.append(draft.quantity)
            draft.quantity = None
        draft.conflicting_quantities.append(quantity)

    drafts.extend(ItemDraft(product=None, quantity=q) for q in loose_quantities)
    for product in loose_products:
        if product.normalized in by_product:
            continue
        by_product[product.normalized] = ItemDraft(product=product, quantity=None)
        drafts.append(by_product[product.normalized])

    return sorted(drafts, key=lambda draft: draft.start)
