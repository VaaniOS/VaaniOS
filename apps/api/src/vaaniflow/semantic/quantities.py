"""Quantity and price/tax extraction."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from vaaniflow.domain.schemas.semantic import TaxInstruction, TaxTreatment, TextSpan
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.lexicon import (
    CURRENCY_PREFIXES,
    CURRENCY_SUFFIXES,
    PER_WORDS,
    PRICE_CUE_FILLERS,
    PRICE_CUES,
    TAX_BARE,
    TAX_EXCLUSIVE,
    TAX_INCLUSIVE,
    UNITS,
)
from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.numbers import NumberParse, iter_numbers
from vaaniflow.semantic.text import Token, char_span, find_phrases, surface

# Tokens after a number that mark a product specification, not a quantity.
_SPEC_SUFFIXES = frozenset({"grade", "mm", "inch", "inches", "mpa", "gauge", "number"})

CURRENCY = "INR"


def _format_amount(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _reserved(parse: NumberParse, reserved: set[int]) -> bool:
    return any(index in reserved for index in range(parse.start, parse.end))


def _has_price_cue(tokens: Sequence[Token], index: int) -> bool:
    """A price cue ("rate", "price", "@") within three filler words before index."""
    position = index - 1
    skipped = 0
    while position >= 0 and skipped <= 3:
        token = tokens[position]
        if token.lower in PRICE_CUES:
            return True
        if token.lower not in PRICE_CUE_FILLERS:
            return False
        position -= 1
        skipped += 1
    return False


def extract_price_mentions(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
) -> list[Mention]:
    mentions: list[Mention] = []

    for parse in iter_numbers(tokens):
        if _reserved(parse, reserved):
            continue

        start = parse.start
        end = parse.end
        currency: str | None = None
        per_unit: str | None = None

        if start > 0 and tokens[start - 1].lower in CURRENCY_PREFIXES:
            start -= 1
            currency = CURRENCY

        if end < len(tokens) and tokens[end].lower in CURRENCY_SUFFIXES:
            currency = CURRENCY
            end += 1

        if (
            end + 1 < len(tokens)
            and (tokens[end].lower in PER_WORDS or tokens[end].lower == "a")
            and tokens[end + 1].lower in UNITS
        ):
            per_unit = UNITS[tokens[end + 1].lower]
            end += 2

        cue = _has_price_cue(tokens, start) or (
            start > 0 and tokens[start - 1].lower == "at" and (currency or per_unit)
        )

        if not (currency or per_unit or cue):
            continue

        if (
            currency is None
            and per_unit is None
            and parse.end < len(tokens)
            and tokens[parse.end].lower in UNITS
        ):
            continue  # "rate ... 200 bags": a quantity, not a price

        markers = sum(1 for marker in (currency, per_unit) if marker)
        score = (
            conf.PRICE_WITH_CURRENCY_AND_UNIT
            if markers == 2
            else conf.PRICE_WITH_ONE_MARKER
            if markers == 1
            else conf.PRICE_CUE_ONLY
        )
        if parse.from_words:
            score -= 0.05

        char_start, char_end = char_span(tokens, start, end)
        mentions.append(
            Mention(
                kind=MentionKind.PRICE,
                start=start,
                end=end,
                surface=surface(text, tokens, start, end),
                normalized=f"{_format_amount(parse.value)} {currency or '?'}/{per_unit or '?'}",
                confidence=score,
                char_start=char_start,
                char_end=char_end,
                value=parse.value,
                currency=currency,
                per_unit=per_unit,
            )
        )
        reserved.update(range(start, end))

    return mentions


def extract_quantity_mentions(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
) -> list[Mention]:
    """
    Number + unit → QUANTITY. Digits (or multiplier number words) without a
    unit → BARE_NUMBER, used for corrections ("200 — actually 220 bags") and
    for "200 UltraTech cement" style binding. Small number words without a
    unit ("bhej do") are ignored.
    """
    mentions: list[Mention] = []

    for parse in iter_numbers(tokens):
        if _reserved(parse, reserved):
            continue

        following = tokens[parse.end].lower if parse.end < len(tokens) else None

        if following in _SPEC_SUFFIXES:
            continue

        score = conf.NUMBER_WORDS if parse.from_words else conf.DIGITS

        if following is not None and following in UNITS:
            end = parse.end + 1
            kind = MentionKind.QUANTITY
            unit: str | None = UNITS[following]
        elif not parse.from_words or parse.has_multiplier:
            end = parse.end
            kind = MentionKind.BARE_NUMBER
            unit = None
        else:
            continue

        char_start, char_end = char_span(tokens, parse.start, end)
        mentions.append(
            Mention(
                kind=kind,
                start=parse.start,
                end=end,
                surface=surface(text, tokens, parse.start, end),
                normalized=f"{_format_amount(parse.value)} {unit or '?'}",
                confidence=score,
                char_start=char_start,
                char_end=char_end,
                value=parse.value,
                unit=unit,
            )
        )
        reserved.update(range(parse.start, end))

    return mentions


def extract_tax(text: str, tokens: Sequence[Token]) -> TaxInstruction | None:
    for candidates, treatment, score in (
        (TAX_EXCLUSIVE, TaxTreatment.EXCLUSIVE, conf.TAX_EXPLICIT),
        (TAX_INCLUSIVE, TaxTreatment.INCLUSIVE, conf.TAX_EXPLICIT),
        (TAX_BARE, TaxTreatment.UNSPECIFIED, conf.TAX_BARE),
    ):
        matches = find_phrases(tokens, candidates)
        if matches:
            match = matches[0]
            char_start, char_end = char_span(tokens, match.start, match.end)
            return TaxInstruction(
                tax_type="GST",
                treatment=treatment,
                surface_text=text[char_start:char_end],
                span=TextSpan(start=char_start, end=char_end),
                confidence=conf.rule(score),
            )
    return None
