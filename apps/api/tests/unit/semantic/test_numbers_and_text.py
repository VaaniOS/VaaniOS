from __future__ import annotations

from decimal import Decimal

import pytest

from vaaniflow.semantic.numbers import iter_numbers
from vaaniflow.semantic.text import TokenKind, tokenize


@pytest.mark.parametrize(
    ("text", "value", "from_words"),
    [
        ("200", Decimal(200), False),
        ("1,000", Decimal(1000), False),
        ("2.5", Decimal("2.5"), False),
        ("chaar sau bees", Decimal(420), True),
        ("do sau", Decimal(200), True),
        ("dhai sau", Decimal(250), True),
        ("ek hazaar paanch sau", Decimal(1500), True),
        ("two hundred and twenty", Decimal(220), True),
        ("fifty", Decimal(50), True),
    ],
)
def test_number_parsing(text: str, value: Decimal, from_words: bool) -> None:
    parses = iter_numbers(tokenize(text))

    assert len(parses) == 1
    assert parses[0].value == value
    assert parses[0].from_words is from_words


def test_tokenizer_keeps_exact_character_offsets() -> None:
    text = "Rs. 420/- per bag—actually ₹410"
    tokens = tokenize(text)

    assert [t.text for t in tokens] == [
        "Rs.",
        "420",
        "/-",
        "per",
        "bag",
        "—",
        "actually",
        "₹",
        "410",
    ]
    assert all(text[t.start : t.end] == t.text for t in tokens)
    assert tokens[0].lower == "rs"
    assert tokens[1].kind is TokenKind.NUMBER


def test_tokenizer_tracks_sentences() -> None:
    tokens = tokenize("Dispatch karo. Invoice bhejo!")

    assert [t.sentence for t in tokens] == [0, 0, 0, 1, 1, 1]
