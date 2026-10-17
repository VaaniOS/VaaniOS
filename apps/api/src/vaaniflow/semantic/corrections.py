"""
Self-correction detection (System-Design 05 §5.5, ADR-012).

A correction is a marker ("actually", "sorry", "nahi nahi", "no,", ...)
followed by a replacement mention of the same kind as a mention just
before the marker:

    "200 bags, actually 220"             QUANTITY 200 bag → 220 bag
    "200—actually 220 bags"              QUANTITY 200 → 220 bag
    "at 420, sorry 410 per bag"          PRICE    420 → 410
    "Sharma Builders ko, nahi nahi, Sharma Buildtech ko"   CUSTOMER
    "UltraTech cement, sorry, ACC cement"                  PRODUCT
    "kal dispatch karo, nahi, parso"                       DATE

Markers are matched as whole tokens, so "now", "know", "notify", "Noida"
or "notebook" never trigger a correction. The superseded mention is kept
in the returned record; the compiler drops it from the current state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from vaaniflow.domain.schemas.semantic import CorrectionField
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.lexicon import CORRECTION_MARKERS, SOFT_NEGATION_MARKERS
from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.temporal import inherit_direction
from vaaniflow.semantic.text import PhraseMatch, Token, find_phrases

_MARKER_PUNCTUATION = frozenset({",", "—", "–", "-", "…", ":"})
_ADDITIVE_WORDS = frozenset({"bhi", "also", "too", "aur", "and", "extra", "more"})
_MAX_GAP_AFTER_MARKER = 4
_MAX_LOOKBACK = 14

_GROUPS: dict[MentionKind, str] = {
    MentionKind.QUANTITY: "numeric",
    MentionKind.BARE_NUMBER: "numeric",
    MentionKind.PRICE: "numeric",
    MentionKind.CUSTOMER: "customer",
    MentionKind.PRODUCT: "product",
    MentionKind.TEMPORAL: "temporal",
}


def _compatible(previous: Mention, replacement: Mention) -> bool:
    """A price never replaces a quantity and vice versa; bare numbers replace either."""
    if _GROUPS[previous.kind] != _GROUPS[replacement.kind]:
        return False
    kinds = {previous.kind, replacement.kind}
    return not (MentionKind.PRICE in kinds and MentionKind.QUANTITY in kinds)


@dataclass(slots=True)
class CorrectionRecord:
    field: CorrectionField
    previous: Mention
    replacement: Mention
    marker: PhraseMatch
    confidence: float


def find_markers(tokens: Sequence[Token]) -> list[PhraseMatch]:
    markers = find_phrases(tokens, CORRECTION_MARKERS)
    covered = {index for marker in markers for index in range(marker.start, marker.end)}

    for token in tokens:
        if token.index in covered or token.lower not in SOFT_NEGATION_MARKERS:
            continue
        previous = tokens[token.index - 1] if token.index > 0 else None
        following = tokens[token.index + 1] if token.index + 1 < len(tokens) else None
        if (following is not None and following.text in _MARKER_PUNCTUATION) or (
            previous is not None and previous.text in _MARKER_PUNCTUATION
        ):
            markers.append(PhraseMatch(token.index, token.index + 1, (token.lower,)))

    return sorted(markers, key=lambda marker: marker.start)


def _field_for(previous: Mention, replacement: Mention) -> CorrectionField:
    kind = _GROUPS[replacement.kind]
    if kind == "customer":
        return CorrectionField.CUSTOMER
    if kind == "product":
        return CorrectionField.PRODUCT
    if kind == "temporal":
        return CorrectionField.DATE
    if MentionKind.PRICE in (previous.kind, replacement.kind):
        return CorrectionField.PRICE
    if (
        previous.value == replacement.value
        and previous.unit is not None
        and replacement.unit is not None
        and previous.unit != replacement.unit
    ):
        return CorrectionField.UNIT
    return CorrectionField.QUANTITY


def _inherit(previous: Mention, replacement: Mention, field: CorrectionField) -> bool:
    """Fill attributes the speaker omitted in the replacement. Returns True if inherited."""
    inherited = False

    if field is CorrectionField.PRICE:
        if replacement.kind is not MentionKind.PRICE:
            replacement.kind = MentionKind.PRICE
            inherited = True
        if replacement.currency is None and previous.currency is not None:
            replacement.currency = previous.currency
            inherited = True
        if replacement.per_unit is None and previous.per_unit is not None:
            replacement.per_unit = previous.per_unit
            inherited = True
        replacement.unit = None
    elif field is CorrectionField.DATE:
        if replacement.temporal is not None and previous.temporal is not None:
            oriented = inherit_direction(replacement.temporal, previous.temporal)
            if oriented is not replacement.temporal:
                replacement.temporal = oriented
                replacement.normalized = oriented.normalized_expression
                replacement.confidence = oriented.confidence.score
    elif field is CorrectionField.QUANTITY:
        if replacement.unit is None and previous.unit is not None:
            replacement.unit = previous.unit
            replacement.kind = MentionKind.QUANTITY
            inherited = True

    if inherited:
        replacement.confidence = min(replacement.confidence, conf.UNIT_INHERITED)
    return inherited


def detect_corrections(
    tokens: Sequence[Token],
    mentions: Sequence[Mention],
) -> list[CorrectionRecord]:
    ordered = sorted(mentions, key=lambda mention: mention.start)
    superseded: set[UUID] = set()
    records: list[CorrectionRecord] = []

    for marker in find_markers(tokens):
        replacement = next(
            (
                mention
                for mention in ordered
                if mention.start >= marker.end
                and mention.start - marker.end <= _MAX_GAP_AFTER_MARKER
                and not any(t.text in {".", "!", "?"} for t in tokens[marker.end : mention.start])
            ),
            None,
        )
        if replacement is None:
            continue

        following = tokens[replacement.end : replacement.end + 2]
        if any(token.lower in _ADDITIVE_WORDS for token in following):
            continue  # "actually Kumar ko bhi" adds, it does not replace

        previous = next(
            (
                mention
                for mention in reversed(ordered)
                if mention.end <= marker.start
                and _compatible(mention, replacement)
                and mention.mention_id not in superseded
                and marker.start - mention.end <= _MAX_LOOKBACK
            ),
            None,
        )
        if previous is None:
            continue

        field = _field_for(previous, replacement)
        inherited = _inherit(previous, replacement, field)
        crosses_sentence = tokens[previous.start].sentence != tokens[replacement.start].sentence
        score = (
            conf.CORRECTION_INFERRED if inherited or crosses_sentence else conf.CORRECTION_ADJACENT
        )

        superseded.add(previous.mention_id)
        records.append(CorrectionRecord(field, previous, replacement, marker, score))

    return records
