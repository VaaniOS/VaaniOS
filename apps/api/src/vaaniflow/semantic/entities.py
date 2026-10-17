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
    DISJUNCTIONS,
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


def _run_before(tokens: Sequence[Token], end: int, reserved: set[int], limit: int) -> int:
    """Start of the name-eligible run ending at ``end`` (== end if empty)."""
    start = end
    while (
        start > 0
        and end - start < limit
        and _name_eligible(tokens[start - 1], reserved)
        and tokens[start - 1].lower not in BUSINESS_SUFFIXES
    ):
        start -= 1
    return start


def _run_after(tokens: Sequence[Token], begin: int, reserved: set[int], limit: int) -> int:
    """End of the name-eligible run starting at ``begin`` (== begin if empty)."""
    end = begin
    while (
        end < len(tokens)
        and end - begin < limit
        and _name_eligible(tokens[end], reserved)
        and tokens[end].lower not in BUSINESS_SUFFIXES
    ):
        end += 1
    return end


def _is_disjunction(tokens: Sequence[Token], index: int) -> bool:
    return 0 <= index < len(tokens) and tokens[index].lower in DISJUNCTIONS


def _with_alternatives(
    text: str,
    tokens: Sequence[Token],
    mention: Mention,
    start: int,
    end: int,
    alternatives: list[str],
) -> Mention:
    """Widen a mention to cover offered alternatives; no single value is chosen."""
    char_start, char_end = char_span(tokens, start, end)
    mention.start, mention.end = start, end
    mention.char_start, mention.char_end = char_start, char_end
    mention.surface = text[char_start:char_end]
    mention.alternatives = alternatives
    mention.normalized = " | ".join(alternative.casefold() for alternative in alternatives)
    return mention


def merge_adjacent_alternatives(
    text: str,
    tokens: Sequence[Token],
    mentions: list[Mention],
) -> list[Mention]:
    """Join "<A> ya <B>" where A and B are both full mentions of one kind."""
    merged: list[Mention] = []
    for mention in sorted(mentions, key=lambda m: m.start):
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.kind is mention.kind
            and mention.start == previous.end + 1
            and _is_disjunction(tokens, previous.end)
            and tokens[previous.start].sentence == tokens[mention.start].sentence
        ):
            alternatives = [
                *(previous.alternatives or [previous.surface]),
                *(mention.alternatives or [mention.surface]),
            ]
            merged[-1] = _with_alternatives(
                text, tokens, previous, previous.start, mention.end, alternatives
            )
            continue
        merged.append(mention)
    return merged


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

        mention = _mention(
            MentionKind.PRODUCT, text, tokens, start, end, conf.PRODUCT_WITH_CATEGORY_NOUN
        )

        # "UltraTech ya ACC cement": brand alternatives sharing one category noun.
        head = text[tokens[index].start : tokens[end - 1].end]
        alternatives = [mention.surface]
        left = start
        while _is_disjunction(tokens, left - 1):
            run_start = _run_before(tokens, left - 1, reserved, _MAX_PRODUCT_MODIFIERS)
            if run_start == left - 1:
                break
            brands = text[tokens[run_start].start : tokens[left - 2].end]
            alternatives.insert(0, f"{brands} {head}")
            left = run_start
        if len(alternatives) > 1:
            mention = _with_alternatives(text, tokens, mention, left, end, alternatives)

        mentions.append(mention)
        reserved.update(range(mention.start, mention.end))
        index = end

    return merge_adjacent_alternatives(text, tokens, mentions)


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

        # "200 bags Birla ya JK dispatch karo": positional alternatives.
        alternatives = [surface(text, tokens, start, end)]
        while _is_disjunction(tokens, end):
            run_end = _run_after(tokens, end + 1, reserved, _MAX_PRODUCT_MODIFIERS)
            if run_end == end + 1:
                break
            alternatives.append(surface(text, tokens, end + 1, run_end))
            end = run_end

        if end < len(tokens) and tokens[end].lower in {"ko", "ke"}:
            continue
        if end < len(tokens) and _name_eligible(tokens[end], reserved):
            continue  # run too long to be a confident product phrase

        mention = _mention(
            MentionKind.PRODUCT, text, tokens, start, end, conf.PRODUCT_POSITIONAL_ONLY
        )
        if len(alternatives) > 1:
            mention = _with_alternatives(text, tokens, mention, start, end, alternatives)
        mentions.append(mention)
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
        mention = _mention(MentionKind.CUSTOMER, text, tokens, start, end, score)

        # "Sharma Builders ya Kumar Constructions ko" / "to Sharma or Kumar".
        alternatives = [mention.surface]
        left, right = start, end
        while _is_disjunction(tokens, left - 1):
            run_start = _backward_name(tokens, left - 1, reserved)
            if run_start is None:
                break
            alternatives.insert(0, surface(text, tokens, run_start, left - 1))
            left = run_start
        while _is_disjunction(tokens, right):
            run_end = _forward_name(tokens, right + 1, reserved)
            if run_end is None:
                break
            alternatives.append(surface(text, tokens, right + 1, run_end))
            right = run_end
        if len(alternatives) > 1:
            mention = _with_alternatives(text, tokens, mention, left, right, alternatives)

        mentions.append(mention)
        reserved.update(range(mention.start, mention.end))

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
