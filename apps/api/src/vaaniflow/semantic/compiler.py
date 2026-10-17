"""
Deterministic semantic compiler: Transcript → SemanticState.

Pipeline (each step is a small module in this package):

    tokenize
      → temporal expressions        (reserve tokens; "15 October" is not a quantity)
      → addressee                   ("Arre Suresh, ...")
      → prices, products, quantities, customers
      → references, tax, corrections
      → item binding, price binding, reference/temporal linking
      → requested actions, intent, urgency
      → semantic ambiguities
      → SemanticState

The compiler understands language only. It does not resolve business IDs,
query business data, validate prices, check inventory, authorise or execute
anything, and it does not judge actionability (Input Evaluation does).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from vaaniflow.domain.schemas.semantic import (
    Ambiguity,
    CompilerProvenance,
    CorrectionEvent,
    CorrectionField,
    CorrectionValue,
    PriceSource,
    ReferenceType,
    RequestedAction,
    RequestedActionType,
    SemanticEntity,
    SemanticEntityType,
    SemanticItem,
    SemanticPrice,
    SemanticQuantity,
    SemanticReference,
    SemanticState,
    TemporalExpression,
    TemporalTarget,
    TextSpan,
)
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic import ambiguity as amb
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.actions import decide_intent, extract_requested_actions, extract_urgency
from vaaniflow.semantic.corrections import CorrectionRecord, detect_corrections
from vaaniflow.semantic.entities import (
    extract_addressee,
    extract_customer_mentions,
    extract_positional_products,
    extract_product_mentions,
)
from vaaniflow.semantic.items import ItemDraft, bind_items
from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.quantities import (
    extract_price_mentions,
    extract_quantity_mentions,
    extract_tax,
)
from vaaniflow.semantic.references import extract_reference_matches
from vaaniflow.semantic.temporal import anchor_to_reference, extract_temporal_mentions
from vaaniflow.semantic.text import Token, tokenize

COMPILER_NAME = "vaaniflow.deterministic-compiler"
COMPILER_VERSION = "2.0.0"

_HISTORICAL_PRICE_REFERENCES = frozenset(
    {ReferenceType.HISTORICAL_PRICE, ReferenceType.HISTORICAL_QUOTE}
)
_EXECUTION_ACTIONS = frozenset(
    {
        RequestedActionType.DISPATCH,
        RequestedActionType.CREATE_ORDER,
        RequestedActionType.UPDATE_ORDER,
        RequestedActionType.CANCEL_ORDER,
    }
)
_REFERENCE_TEMPORAL_WINDOW_AFTER = 6
_REFERENCE_TEMPORAL_WINDOW_BEFORE = 3


def _span(mention: Mention) -> TextSpan:
    return TextSpan(start=mention.char_start, end=mention.char_end)


def _entity(mention: Mention, entity_type: SemanticEntityType) -> SemanticEntity:
    return SemanticEntity(
        entity_id=mention.mention_id,
        entity_type=entity_type,
        surface_text=mention.surface,
        normalized_text=mention.normalized,
        span=_span(mention),
        confidence=conf.rule(mention.confidence),
    )


def _quantity(mention: Mention) -> SemanticQuantity:
    assert mention.value is not None
    return SemanticQuantity(
        value=mention.value,
        unit=mention.unit,
        surface_text=mention.surface,
        span=_span(mention),
        confidence=conf.rule(mention.confidence),
    )


def _correction_value(mention: Mention, field: CorrectionField) -> CorrectionValue:
    numeric = field in (CorrectionField.QUANTITY, CorrectionField.UNIT, CorrectionField.PRICE)
    if numeric and mention.value is not None:
        unit = mention.per_unit if field is CorrectionField.PRICE else mention.unit
        amount = format(mention.value.normalize(), "f")
        normalized = f"{amount} {unit}" if unit else amount
    else:
        normalized = mention.normalized
    return CorrectionValue(
        surface_text=mention.surface,
        normalized=normalized,
        amount=mention.value if numeric else None,
        unit=(mention.per_unit if field is CorrectionField.PRICE else mention.unit)
        if numeric
        else None,
        span=_span(mention),
    )


class SemanticCompiler:
    """Deterministic, rule-based Transcript → SemanticState compiler."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def compile(self, transcript: Transcript, *, run_id: UUID | None = None) -> SemanticState:
        text = transcript.text
        tokens = tokenize(text)
        reserved: set[int] = set()

        temporal = extract_temporal_mentions(text, tokens)
        for mention in temporal:
            reserved.update(mention.tokens())

        addressee = extract_addressee(text, tokens, reserved)
        prices = extract_price_mentions(text, tokens, reserved)
        products = extract_product_mentions(text, tokens, reserved)
        quantities = extract_quantity_mentions(text, tokens, reserved)
        products += extract_positional_products(text, tokens, reserved, quantities)

        reference_matches = extract_reference_matches(text, tokens)
        for _, start, end in reference_matches:
            reserved.update(range(start, end))

        customers = extract_customer_mentions(text, tokens, reserved)
        tax = extract_tax(text, tokens)

        records = detect_corrections(
            tokens, [*temporal, *prices, *products, *quantities, *customers]
        )
        replacements = {record.previous.mention_id: record.replacement for record in records}
        superseded = set(replacements)

        def alive(mentions: Sequence[Mention], kind: MentionKind) -> list[Mention]:
            return [m for m in mentions if m.kind is kind and m.mention_id not in superseded]

        numeric = [*quantities, *prices]
        ambiguities: list[Ambiguity] = []

        # Customer ---------------------------------------------------------- #
        live_customers = alive(customers, MentionKind.CUSTOMER)
        distinct_customers = {m.normalized: m for m in live_customers}
        customer: SemanticEntity | None = None
        if len(distinct_customers) == 1:
            customer = _entity(next(iter(distinct_customers.values())), SemanticEntityType.CUSTOMER)
        elif len(distinct_customers) > 1:
            ambiguities.append(amb.competing_customers([m.surface for m in live_customers]))

        # Items ------------------------------------------------------------- #
        drafts = bind_items(
            tokens,
            [m for m in numeric if m.kind in (MentionKind.QUANTITY, MentionKind.BARE_NUMBER)],
            [m for m in products if m.kind is MentionKind.PRODUCT],
            replacements,
        )
        items = [self._item(draft) for draft in drafts]
        for draft in drafts:
            if draft.conflicting_quantities and draft.product is not None:
                ambiguities.append(
                    amb.conflicting_quantities(
                        draft.product.surface,
                        [m.surface for m in draft.conflicting_quantities],
                        draft.item_id,
                    )
                )

        # References and their temporal anchors ----------------------------- #
        temporal_by_id = {
            m.mention_id: m.temporal
            for m in alive(temporal, MentionKind.TEMPORAL)
            if m.temporal is not None
        }
        temporal_mentions = {m.mention_id: m for m in temporal if m.mention_id in temporal_by_id}
        references: list[SemanticReference] = []
        for reference, start, end in reference_matches:
            linked = self._linked_temporal(tokens, start, end, temporal_mentions.values())
            item_id = self._reference_item(reference, start, drafts)
            if linked is not None:
                expression = temporal_by_id[linked.mention_id]
                temporal_by_id[linked.mention_id] = anchor_to_reference(
                    expression, reference.surface_text
                )
            references.append(
                SemanticReference.model_validate(
                    {
                        **reference.model_dump(),
                        "item_id": item_id,
                        "temporal_expression_id": linked.mention_id if linked else None,
                    }
                )
            )

        # Requested actions and intent --------------------------------------- #
        marker_tokens = {
            i for record in records for i in range(record.marker.start, record.marker.end)
        }
        goods_tokens = {
            i
            for draft in drafts
            for m in (draft.product, draft.quantity)
            if m is not None
            for i in m.tokens()
        }
        # "send it" / "usko bhejo": the pronoun object stands for the goods.
        goods_tokens.update(
            i
            for reference, start, end in reference_matches
            if reference.reference_type in (ReferenceType.PRONOUN, ReferenceType.PRODUCT)
            for i in range(start, end)
        )
        actions = extract_requested_actions(
            text,
            tokens,
            goods_tokens=goods_tokens,
            customer_tokens={i for m in live_customers for i in m.tokens()},
            correction_tokens=marker_tokens,
        )
        decision = decide_intent(actions)
        if decision.conflicting:
            ambiguities.append(amb.competing_actions(decision.conflicting))

        temporal_expressions = self._target_temporal(
            tokens, temporal_mentions, temporal_by_id, actions
        )
        ambiguities.extend(amb.temporal_ambiguities(temporal_expressions))

        # Pricing ------------------------------------------------------------ #
        pricing, price_ambiguities, price_ids = self._pricing(
            tokens,
            [m for m in numeric if m.kind is MentionKind.PRICE and m.mention_id not in superseded],
            references,
            reference_matches,
            drafts,
        )
        ambiguities.extend(price_ambiguities)

        corrections = [self._correction(text, record, drafts, price_ids) for record in records]

        return SemanticState(
            semantic_state_id=uuid4(),
            run_id=run_id,
            source_transcript_id=transcript.transcript_id,
            compiler=CompilerProvenance(
                compiler_name=COMPILER_NAME, compiler_version=COMPILER_VERSION
            ),
            intent=decision.intent,
            intent_confidence=conf.rule(decision.confidence),
            customer=customer,
            addressee=_entity(addressee, SemanticEntityType.PERSON) if addressee else None,
            items=items,
            pricing=pricing,
            tax=tax,
            references=references,
            temporal_expressions=temporal_expressions,
            corrections=corrections,
            ambiguities=ambiguities,
            requested_actions=actions,
            urgency=extract_urgency(tokens),
            created_at=self._clock(),
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _item(draft: ItemDraft) -> SemanticItem:
        return SemanticItem(
            item_id=draft.item_id,
            product=_entity(draft.product, SemanticEntityType.PRODUCT) if draft.product else None,
            quantity=_quantity(draft.quantity) if draft.quantity else None,
        )

    @staticmethod
    def _linked_temporal(
        tokens: Sequence[Token],
        start: int,
        end: int,
        temporal: Iterable[Mention],
    ) -> Mention | None:
        sentence = tokens[start].sentence
        for mention in temporal:
            if tokens[mention.start].sentence != sentence:
                continue
            after = 0 <= mention.start - end <= _REFERENCE_TEMPORAL_WINDOW_AFTER
            before = 0 <= start - mention.end <= _REFERENCE_TEMPORAL_WINDOW_BEFORE
            if after or before:
                return mention
        return None

    @staticmethod
    def _reference_item(
        reference: SemanticReference,
        start: int,
        drafts: Sequence[ItemDraft],
    ) -> UUID | None:
        """Attach "200 bags of the same product" to the item it completes."""
        if reference.reference_type is not ReferenceType.PRODUCT:
            return None
        for draft in drafts:
            if (
                draft.product is None
                and draft.quantity is not None
                and 0 <= start - draft.quantity.end <= 2
            ):
                return draft.item_id
        return None

    @staticmethod
    def _target_temporal(
        tokens: Sequence[Token],
        mentions: dict[UUID, Mention],
        expressions: dict[UUID, TemporalExpression],
        actions: Sequence[RequestedAction],
    ) -> list[TemporalExpression]:
        by_char = {token.start: token for token in tokens}
        execution_sentences = {
            by_char[action.span.start].sentence
            for action in actions
            if action.action_type in _EXECUTION_ACTIONS and action.span.start in by_char
        }
        result: list[TemporalExpression] = []
        for mention_id, expression in expressions.items():
            if (
                expression.target is TemporalTarget.UNSPECIFIED
                and tokens[mentions[mention_id].start].sentence in execution_sentences
            ):
                expression = TemporalExpression.model_validate(
                    {**expression.model_dump(), "target": TemporalTarget.EXECUTION}
                )
            result.append(expression)
        return sorted(result, key=lambda expression: expression.span.start)

    @staticmethod
    def _price_item(
        tokens: Sequence[Token],
        start: int,
        per_unit: str | None,
        drafts: Sequence[ItemDraft],
    ) -> UUID | None:
        if len(drafts) == 1:
            return drafts[0].item_id
        if per_unit is not None:
            matching = [draft for draft in drafts if draft.unit == per_unit]
            if len(matching) == 1:
                return matching[0].item_id
        sentence = tokens[start].sentence
        for draft in drafts:
            if tokens[draft.start].sentence == sentence and 0 <= start - draft.end <= 3:
                return draft.item_id
        return None

    def _pricing(
        self,
        tokens: Sequence[Token],
        spoken: Sequence[Mention],
        references: Sequence[SemanticReference],
        reference_matches: Sequence[tuple[SemanticReference, int, int]],
        drafts: Sequence[ItemDraft],
    ) -> tuple[list[SemanticPrice], list[Ambiguity], dict[UUID, UUID]]:
        reference_tokens = {
            ref.reference_id: (start, end) for (ref, start, end) in reference_matches
        }
        historical = [
            reference
            for reference in references
            if reference.reference_type in _HISTORICAL_PRICE_REFERENCES
        ]
        used_references: set[UUID] = set()
        pricing: list[SemanticPrice] = []
        ambiguities: list[Ambiguity] = []
        price_ids: dict[UUID, UUID] = {}

        for mention in spoken:
            assert mention.value is not None
            sentence = tokens[mention.start].sentence
            linked = next(
                (
                    reference
                    for reference in historical
                    if reference.reference_id not in used_references
                    and tokens[reference_tokens[reference.reference_id][0]].sentence == sentence
                ),
                None,
            )
            if linked is not None:
                used_references.add(linked.reference_id)

            price = SemanticPrice(
                price_id=uuid4(),
                source=(
                    PriceSource.SPOKEN_WITH_HISTORICAL_REFERENCE if linked else PriceSource.SPOKEN
                ),
                amount=mention.value,
                currency=mention.currency,
                per_unit=mention.per_unit,
                item_id=self._price_item(tokens, mention.start, mention.per_unit, drafts),
                reference_id=linked.reference_id if linked else None,
                surface_text=mention.surface,
                span=_span(mention),
                confidence=conf.rule(mention.confidence),
            )
            price_ids[mention.mention_id] = price.price_id
            pricing.append(price)

        for reference in historical:
            if reference.reference_id in used_references:
                continue
            start, _ = reference_tokens[reference.reference_id]
            pricing.append(
                SemanticPrice(
                    price_id=uuid4(),
                    source=PriceSource.HISTORICAL_REFERENCE,
                    item_id=self._price_item(tokens, start, None, drafts),
                    reference_id=reference.reference_id,
                    surface_text=reference.surface_text,
                    span=reference.span,
                    confidence=reference.confidence,
                )
            )

        for price in pricing:
            if price.item_id is None and len(drafts) > 1:
                ambiguities.append(
                    amb.unscoped_price(
                        price.surface_text, price.price_id, [d.item_id for d in drafts]
                    )
                )

        by_item: dict[UUID | None, list[SemanticPrice]] = {}
        for price in pricing:
            if price.amount is not None:
                by_item.setdefault(price.item_id, []).append(price)
        for group in by_item.values():
            if len({(price.amount, price.per_unit) for price in group}) > 1:
                ambiguities.append(
                    amb.conflicting_prices(
                        [price.surface_text for price in group],
                        [price.price_id for price in group],
                    )
                )

        return sorted(pricing, key=lambda p: p.span.start), ambiguities, price_ids

    @staticmethod
    def _correction(
        text: str,
        record: CorrectionRecord,
        drafts: Sequence[ItemDraft],
        price_ids: dict[UUID, UUID],
    ) -> CorrectionEvent:
        replacement = record.replacement
        target_id: UUID | None
        if record.field is CorrectionField.PRICE:
            target_id = price_ids.get(replacement.mention_id)
        elif record.field in (CorrectionField.QUANTITY, CorrectionField.UNIT):
            target_id = next(
                (
                    draft.item_id
                    for draft in drafts
                    if draft.quantity is not None
                    and draft.quantity.mention_id == replacement.mention_id
                ),
                None,
            )
        elif record.field is CorrectionField.PRODUCT:
            target_id = next(
                (
                    draft.item_id
                    for draft in drafts
                    if draft.product is not None
                    and draft.product.mention_id == replacement.mention_id
                ),
                None,
            )
        else:
            target_id = replacement.mention_id

        start = min(record.previous.char_start, replacement.char_start)
        end = max(record.previous.char_end, replacement.char_end)
        marker_tokens = " ".join(record.marker.words)

        return CorrectionEvent(
            correction_id=uuid4(),
            field=record.field,
            previous_value=_correction_value(record.previous, record.field),
            corrected_value=_correction_value(replacement, record.field),
            marker=marker_tokens,
            target_id=target_id,
            source_text=text[start:end],
            confidence=conf.rule(record.confidence),
        )
