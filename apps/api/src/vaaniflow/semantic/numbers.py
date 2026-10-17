"""
Number parsing for digits and spoken number words (English and romanised
Hindi), because ASR in verbatim mode emits spoken forms such as
"chaar sau bees" (420) or "two hundred" (200).

Supported Hindi words: units 1–19, tens 20–90, "dedh"/"dhai" fractions and
the multipliers sau / hazaar / lakh. Irregular Hindi compounds for 21–99
(e.g. "ikkis", "pachchis") are not supported.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from vaaniflow.semantic.text import Token, TokenKind

_ENGLISH_UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen",
)  # fmt: skip

_VALUES: dict[str, Decimal] = {
    # English
    **{word: Decimal(value) for value, word in enumerate(_ENGLISH_UNITS)},
    "twenty": Decimal(20),
    "thirty": Decimal(30),
    "forty": Decimal(40),
    "fifty": Decimal(50),
    "sixty": Decimal(60),
    "seventy": Decimal(70),
    "eighty": Decimal(80),
    "ninety": Decimal(90),
    # Romanised Hindi
    "ek": Decimal(1),
    "do": Decimal(2),
    "teen": Decimal(3),
    "char": Decimal(4),
    "chaar": Decimal(4),
    "paanch": Decimal(5),
    "panch": Decimal(5),
    "chhe": Decimal(6),
    "chhah": Decimal(6),
    "saat": Decimal(7),
    "aath": Decimal(8),
    "nau": Decimal(9),
    "das": Decimal(10),
    "gyarah": Decimal(11),
    "barah": Decimal(12),
    "baarah": Decimal(12),
    "terah": Decimal(13),
    "chaudah": Decimal(14),
    "pandrah": Decimal(15),
    "solah": Decimal(16),
    "satrah": Decimal(17),
    "atharah": Decimal(18),
    "unnis": Decimal(19),
    "bees": Decimal(20),
    "bis": Decimal(20),
    "tees": Decimal(30),
    "chalis": Decimal(40),
    "chaalis": Decimal(40),
    "pachas": Decimal(50),
    "pachaas": Decimal(50),
    "saath": Decimal(60),
    "sattar": Decimal(70),
    "assi": Decimal(80),
    "nabbe": Decimal(90),
    "dedh": Decimal("1.5"),
    "dhai": Decimal("2.5"),
    "dhaai": Decimal("2.5"),
}

_HUNDREDS = frozenset({"hundred", "sau"})
_LARGE: dict[str, Decimal] = {
    "thousand": Decimal(1000),
    "hazaar": Decimal(1000),
    "hazar": Decimal(1000),
    "lakh": Decimal(100000),
    "lac": Decimal(100000),
}


@dataclass(frozen=True, slots=True)
class NumberParse:
    value: Decimal
    start: int
    end: int
    from_words: bool
    has_multiplier: bool


def _parse_digits(token: Token) -> Decimal | None:
    try:
        return Decimal(token.text.replace(",", ""))
    except InvalidOperation:
        return None


def parse_number_at(tokens: Sequence[Token], index: int) -> NumberParse | None:
    """Parse a number starting exactly at ``tokens[index]``."""
    if index >= len(tokens):
        return None

    token = tokens[index]

    if token.kind is TokenKind.NUMBER:
        value = _parse_digits(token)
        if value is None:
            return None
        return NumberParse(value, index, index + 1, from_words=False, has_multiplier=False)

    if token.lower not in _VALUES and token.lower not in _HUNDREDS and token.lower not in _LARGE:
        return None

    total = Decimal(0)
    current = Decimal(0)
    position = index
    has_multiplier = False
    consumed = False

    while position < len(tokens):
        word = tokens[position].lower

        if word in _VALUES:
            current += _VALUES[word]
        elif word in _HUNDREDS:
            current = (current or Decimal(1)) * 100
            has_multiplier = True
        elif word in _LARGE:
            total += (current or Decimal(1)) * _LARGE[word]
            current = Decimal(0)
            has_multiplier = True
        elif (
            word == "and"
            and consumed
            and position + 1 < len(tokens)
            and tokens[position + 1].lower in _VALUES
            and tokens[position - 1].lower in (_HUNDREDS | _LARGE.keys())
        ):
            pass
        else:
            break

        consumed = True
        position += 1

    value = total + current
    if value <= 0:
        return None

    return NumberParse(value, index, position, from_words=True, has_multiplier=has_multiplier)


def iter_numbers(tokens: Sequence[Token]) -> list[NumberParse]:
    """All maximal, non-overlapping number parses in token order."""
    parses: list[NumberParse] = []
    index = 0

    while index < len(tokens):
        parsed = parse_number_at(tokens, index)
        if parsed is None:
            index += 1
            continue
        parses.append(parsed)
        index = parsed.end

    return parses


def is_number_word(word: str) -> bool:
    return word in _VALUES or word in _HUNDREDS or word in _LARGE
