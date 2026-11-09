"""
Reference extraction (System-Design 05 §5.6).

The compiler records *that* the user referred to something ("same rate",
"previous quote", "that order", "it") and which semantic slot the reference
fills. It never resolves the reference: context resolution does that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from vaaniflow.domain.schemas.semantic import (
    ReferenceType,
    SemanticReference,
    SemanticSlot,
    TextSpan,
)
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.text import Token, char_span, find_phrases, phrases, tokenize


@dataclass(frozen=True, slots=True)
class _Pattern:
    reference_type: ReferenceType
    slot: SemanticSlot
    surfaces: tuple[str, ...]


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        ReferenceType.CUSTOMER,
        SemanticSlot.CUSTOMER,
        (
            "same customer",
            "that customer",
            "same client",
            "same party",
            "previous customer",
            "usi customer",
            "wahi customer",
            "wahi party",
            "usi party",
        ),
    ),
    _Pattern(
        ReferenceType.PRODUCT,
        SemanticSlot.PRODUCT,
        (
            "same product",
            "that product",
            "same item",
            "that item",
            "same material",
            "same maal",
            "wahi maal",
            "wahi product",
            "usi product",
        ),
    ),
    _Pattern(
        ReferenceType.HISTORICAL_PRICE,
        SemanticSlot.PRICE,
        (
            "same rate",
            "same price",
            "usual rate",
            "usual price",
            "old rate",
            "previous rate",
            "last rate",
            "earlier rate",
            "agreed rate",
            "rate wahi",
            "wahi rate",
            "usi rate",
            "rate same",
            "pichhla rate",
            "pichla rate",
            "purana rate",
            "rate we discussed",
            "price we discussed",
            "rate discussed earlier",
            "price discussed earlier",
            "rate quoted",
            "quoted rate",
            "quoted price",
            "rate told",
            "rate given",
        ),
    ),
    _Pattern(
        ReferenceType.HISTORICAL_QUOTE,
        SemanticSlot.QUOTE,
        (
            "previous quote",
            "last quote",
            "earlier quote",
            "old quote",
            "same quote",
            "previous quotation",
            "last quotation",
            "pichhla quote",
            "wahi quote",
        ),
    ),
    _Pattern(
        ReferenceType.ORDER,
        SemanticSlot.ORDER,
        (
            "that order",
            "same order",
            "previous order",
            "last order",
            "earlier order",
            "wahi order",
            "usi order",
            "pichhla order",
        ),
    ),
    _Pattern(
        ReferenceType.PREVIOUS_VALUE,
        SemanticSlot.QUANTITY,
        ("same quantity", "utna hi", "utne hi", "wahi quantity"),
    ),
    _Pattern(
        ReferenceType.PREVIOUS_VALUE,
        SemanticSlot.UNKNOWN,
        ("previous value", "earlier value", "earlier number", "same as last time"),
    ),
)

_PHRASE_TABLE: dict[tuple[str, ...], _Pattern] = {
    words: pattern for pattern in _PATTERNS for words in phrases(pattern.surfaces)
}
_ALL_PHRASES = tuple(sorted(_PHRASE_TABLE, key=len, reverse=True))

# Pronoun objects of an action verb: "send it", "dispatch them", "cancel it".
_ENGLISH_PRONOUNS = frozenset({"it", "them", "those", "these"})
_ENGLISH_ACTION_VERBS = frozenset(
    {"send", "dispatch", "ship", "deliver", "cancel", "invoice", "bill", "approve", "update"}
)
# Hindi object pronoun before a verb: "usko bhejo", "woh cancel karo".
_HINDI_PRONOUNS = frozenset({"usko", "isko", "use", "woh", "wo", "vo", "ye", "yeh"})
_HINDI_ACTION_VERBS = frozenset(
    {"bhejo", "bhej", "bhejdo", "dispatch", "cancel", "deliver", "bhijwa", "bhijwao"}
)
_ORDER_VERBS = frozenset({"cancel", "update", "invoice", "bill", "approve"})


def _reference(
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    reference_type: ReferenceType,
    slot: SemanticSlot,
    score: float,
) -> tuple[SemanticReference, int, int]:
    char_start, char_end = char_span(tokens, start, end)
    words = " ".join(token.lower for token in tokens[start:end])
    reference = SemanticReference(
        reference_id=uuid4(),
        reference_type=reference_type,
        target_slot=slot,
        surface_text=text[char_start:char_end],
        normalized_text=words,
        span=TextSpan(start=char_start, end=char_end),
        confidence=conf.rule(score),
    )
    return reference, start, end


def extract_reference_matches(
    text: str,
    tokens: Sequence[Token],
) -> list[tuple[SemanticReference, int, int]]:
    """References with their token ranges, in transcript order."""
    found: list[tuple[SemanticReference, int, int]] = []

    for match in find_phrases(tokens, _ALL_PHRASES):
        pattern = _PHRASE_TABLE[match.words]
        found.append(
            _reference(
                text,
                tokens,
                match.start,
                match.end,
                pattern.reference_type,
                pattern.slot,
                conf.REFERENCE_PHRASE,
            )
        )

    for token in tokens:
        position = token.index
        verb: str | None = None

        if (
            token.lower in _ENGLISH_PRONOUNS
            and position > 0
            and tokens[position - 1].lower in _ENGLISH_ACTION_VERBS
        ):
            verb = tokens[position - 1].lower
        elif (
            token.lower in _HINDI_PRONOUNS
            and position + 1 < len(tokens)
            and tokens[position + 1].lower in _HINDI_ACTION_VERBS
        ):
            verb = tokens[position + 1].lower

        if verb is None:
            continue

        slot = SemanticSlot.ORDER if verb in _ORDER_VERBS else SemanticSlot.UNKNOWN
        found.append(
            _reference(
                text,
                tokens,
                position,
                position + 1,
                ReferenceType.PRONOUN,
                slot,
                conf.REFERENCE_PRONOUN,
            )
        )

    found.sort(key=lambda entry: entry[1])
    return found


def extract_references(text: str) -> list[SemanticReference]:
    """Convenience wrapper returning only the references."""
    return [reference for reference, _, _ in extract_reference_matches(text, tokenize(text))]
