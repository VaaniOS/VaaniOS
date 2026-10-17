"""
Product, customer and addressee mention extraction.

Names are kept exactly as spoken. Nothing here looks up customers or
products: deciding which record "Sharma Builders" means is context
resolution's job.
"""

from __future__ import annotations

from collections.abc import Sequence

from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.lexicon import (
    BUSINESS_SUFFIXES,
    INTERJECTIONS,
    NAME_STOPWORDS,
    PRODUCT_HEADS,
    UNITS,
)
from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.numbers import is_number_word
from vaaniflow.semantic.text import Token, TokenKind, char_span, surface

_MAX_NAME_TOKENS = 4
_MAX_PRODUCT_MODIFIERS = 3
_LINKERS = frozenset({"of", "ka", "ki", "ke"})
_TELL_VERBS = frozenset({"bolo", "batao", "bata", "kaho", "bol", "bataiye", "call", "phone"})


def _name_eligible(token: Token, reserved: set[int]) -> bool:
    return (
        token.kind is TokenKind.WORD
        and token.index not in reserved
        and token.lower not in NAME_STOPWORDS
        and token.lower not in UNITS
        and not is_number_word(token.lower)
    )


def _mention(
    kind: MentionKind,
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    score: float,
) -> Mention:
    char_start, char_end = char_span(tokens, start, end)
    return Mention(
        kind=kind,
        start=start,
        end=end,
        surface=surface(text, tokens, start, end),
        normalized=" ".join(token.lower for token in tokens[start:end]),
        confidence=score,
        char_start=char_start,
        char_end=char_end,
    )


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #


def extract_product_mentions(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
) -> list[Mention]:
    """
    A product phrase is up to three modifiers (brand/variant) followed by one
    or more category nouns: "UltraTech cement", "JSW TMT bars", "steel rods".
    """
    mentions: list[Mention] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.index in reserved or token.lower not in PRODUCT_HEADS:
            index += 1
            continue

        end = index + 1
        while end < len(tokens) and end not in reserved and tokens[end].lower in PRODUCT_HEADS:
            end += 1

        start = index
        while (
            start > 0
            and index - start < _MAX_PRODUCT_MODIFIERS
            and _name_eligible(tokens[start - 1], reserved)
            and tokens[start - 1].lower not in BUSINESS_SUFFIXES
        ):
            start -= 1

        mentions.append(
            _mention(MentionKind.PRODUCT, text, tokens, start, end, conf.PRODUCT_WITH_CATEGORY_NOUN)
        )
        reserved.update(range(start, end))
        index = end

    return mentions


def extract_positional_products(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
    quantities: Sequence[Mention],
) -> list[Mention]:
    """
    Fallback for products without a known category noun: the words directly
    after "<quantity> <unit> [of]". Rejected when the run is immediately
    followed by "ko"/"ke liye", because then it is a customer name.
    """
    mentions: list[Mention] = []

    for quantity in quantities:
        if quantity.kind is not MentionKind.QUANTITY:
            continue

        start = quantity.end
        if start < len(tokens) and tokens[start].lower in _LINKERS:
            start += 1

        end = start
        while (
            end < len(tokens)
            and end - start < _MAX_PRODUCT_MODIFIERS
            and _name_eligible(tokens[end], reserved)
            and tokens[end].lower not in BUSINESS_SUFFIXES
        ):
            end += 1

        if end == start:
            continue
        if end < len(tokens) and tokens[end].lower in {"ko", "ke"}:
            continue
        if end < len(tokens) and _name_eligible(tokens[end], reserved):
            continue  # run too long to be a confident product phrase

        mentions.append(
            _mention(MentionKind.PRODUCT, text, tokens, start, end, conf.PRODUCT_POSITIONAL_ONLY)
        )
        reserved.update(range(start, end))

    return mentions


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #


def _name_score(tokens: Sequence[Token]) -> float:
    if tokens[-1].lower in BUSINESS_SUFFIXES:
        return conf.CUSTOMER_WITH_BUSINESS_SUFFIX
    if all(token.text[:1].isupper() for token in tokens):
        return conf.CUSTOMER_CAPITALISED
    return conf.CUSTOMER_LOWERCASE


def _backward_name(tokens: Sequence[Token], marker: int, reserved: set[int]) -> int | None:
    start = marker
    while (
        start > 0
        and marker - start < _MAX_NAME_TOKENS
        and _name_eligible(tokens[start - 1], reserved)
    ):
        start -= 1
    return start if start < marker else None


def _forward_name(tokens: Sequence[Token], begin: int, reserved: set[int]) -> int | None:
    end = begin
    while (
        end < len(tokens)
        and end - begin < _MAX_NAME_TOKENS
        and _name_eligible(tokens[end], reserved)
    ):
        end += 1
    return end if end > begin else None


def extract_customer_mentions(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
) -> list[Mention]:
    """
    Customer patterns:
      "<Name> ko"            (Hinglish dative)
      "<Name> ke liye"       (Hinglish "for")
      "to <Name>" / "for <Name>"   (English; capitalised or business-suffixed)
      "customer <Name>" / "party <Name>"
    """
    mentions: list[Mention] = []

    def add(start: int, end: int) -> None:
        name_tokens = tokens[start:end]
        score = _name_score(name_tokens)
        # "arre suresh sharma builders ko" (no comma): the first word may be
        # the addressee or part of the name. Keep the span, but do not let
        # the guess pass as confident.
        if start == 1 and tokens[0].lower in INTERJECTIONS and len(name_tokens) > 1:
            score = conf.CUSTOMER_ADDRESSEE_OVERLAP
        mentions.append(_mention(MentionKind.CUSTOMER, text, tokens, start, end, score))
        reserved.update(range(start, end))

    for token in tokens:
        position = token.index
        if position in reserved:
            continue

        if token.lower == "ko":
            following = tokens[position + 1].lower if position + 1 < len(tokens) else None
            if following in _TELL_VERBS:
                continue
            start = _backward_name(tokens, position, reserved)
            if start is not None:
                add(start, position)
            continue

        if (
            token.lower == "ke"
            and position + 1 < len(tokens)
            and tokens[position + 1].lower == "liye"
        ):
            start = _backward_name(tokens, position, reserved)
            if start is not None:
                add(start, position)
            continue

        if token.lower in {"to", "for", "customer", "party"}:
            end = _forward_name(tokens, position + 1, reserved)
            if end is None:
                continue
            name_tokens = tokens[position + 1 : end]
            anchored = token.lower in {"customer", "party"}
            if (
                anchored
                or name_tokens[-1].lower in BUSINESS_SUFFIXES
                or all(t.text[:1].isupper() for t in name_tokens)
            ):
                add(position + 1, end)

    return mentions


def extract_addressee(
    text: str,
    tokens: Sequence[Token],
    reserved: set[int],
) -> Mention | None:
    """The employee being instructed: "Arre Suresh, ..." / "Suresh ji, ..."."""
    if not tokens:
        return None

    position = 0
    score = conf.ADDRESSEE_LEADING_NAME
    if tokens[0].lower in INTERJECTIONS:
        position = 1
        score = conf.ADDRESSEE_AFTER_INTERJECTION

    end = position
    while end < len(tokens) and end - position < 2 and _name_eligible(tokens[end], reserved):
        end += 1

    if end == position or end >= len(tokens):
        return None
    if tokens[end].text not in {",", "!"} and tokens[end].lower != "ji":
        return None

    name_tokens = tokens[position:end]
    if any(t.lower in BUSINESS_SUFFIXES for t in name_tokens):
        return None
    if position == 0 and not all(t.text[:1].isupper() for t in name_tokens):
        return None

    reserved.update(range(position, end))
    return _mention(MentionKind.CUSTOMER, text, tokens, position, end, score)
