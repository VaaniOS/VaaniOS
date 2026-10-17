"""
Tokenisation primitives for the deterministic semantic compiler.

Every rule in the compiler works on tokens with character offsets into the
original transcript text, so extracted mentions carry exact spans and all
matching is word-bounded (no substring matching inside words such as
"now" / "Kalyan").
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class TokenKind(StrEnum):
    WORD = "WORD"
    NUMBER = "NUMBER"
    PUNCT = "PUNCT"


_TOKEN_PATTERN = re.compile(
    r"\b(?i:rs|pvt|ltd)\.(?!\w)"  # abbreviations whose dot is not punctuation
    r"|(?P<number>\d+(?:,\d+)*(?:\.\d+)?)"
    r"|(?P<word>[^\W\d_]+(?:['’][^\W\d_]+)?)"
    r"|/-|₹|[^\w\s]"
)

SENTENCE_BOUNDARIES = frozenset({".", "!", "?", ";"})


@dataclass(frozen=True, slots=True)
class Token:
    index: int
    text: str
    lower: str
    start: int
    end: int
    kind: TokenKind
    sentence: int

    @property
    def is_punct(self) -> bool:
        return self.kind is TokenKind.PUNCT


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    sentence = 0

    for match in _TOKEN_PATTERN.finditer(text):
        raw = match.group(0)

        if match.group("number") is not None:
            kind = TokenKind.NUMBER
        elif match.group("word") is not None or raw[0].isalpha():
            kind = TokenKind.WORD
        else:
            kind = TokenKind.PUNCT

        lower = (
            raw.casefold().rstrip(".").replace("’", "'")
            if kind is TokenKind.WORD
            else raw.casefold()
        )

        tokens.append(
            Token(
                index=len(tokens),
                text=raw,
                lower=lower,
                start=match.start(),
                end=match.end(),
                kind=kind,
                sentence=sentence,
            )
        )

        if kind is TokenKind.PUNCT and raw in SENTENCE_BOUNDARIES:
            sentence += 1

    return tokens


def phrase(value: str) -> tuple[str, ...]:
    """Split a lexicon phrase into lower-cased token texts."""
    return tuple(token.lower for token in tokenize(value))


def phrases(values: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    """Lexicon phrases sorted longest-first so longer phrases win."""
    return tuple(sorted({phrase(value) for value in values}, key=len, reverse=True))


def matches_at(tokens: Sequence[Token], index: int, words: tuple[str, ...]) -> bool:
    if index < 0 or index + len(words) > len(tokens):
        return False
    return all(tokens[index + offset].lower == word for offset, word in enumerate(words))


def match_any_at(
    tokens: Sequence[Token],
    index: int,
    candidates: tuple[tuple[str, ...], ...],
) -> tuple[str, ...] | None:
    for words in candidates:
        if matches_at(tokens, index, words):
            return words
    return None


@dataclass(frozen=True, slots=True)
class PhraseMatch:
    start: int
    end: int
    words: tuple[str, ...]


def find_phrases(
    tokens: Sequence[Token],
    candidates: tuple[tuple[str, ...], ...],
    *,
    reserved: set[int] | frozenset[int] = frozenset(),
) -> list[PhraseMatch]:
    """Non-overlapping, longest-first phrase matches outside reserved tokens."""
    found: list[PhraseMatch] = []
    index = 0

    while index < len(tokens):
        words = match_any_at(tokens, index, candidates)
        if words is not None and not any(i in reserved for i in range(index, index + len(words))):
            found.append(PhraseMatch(index, index + len(words), words))
            index += len(words)
        else:
            index += 1

    return found


def char_span(tokens: Sequence[Token], start: int, end: int) -> tuple[int, int]:
    """Character range covered by tokens ``[start, end)``."""
    return tokens[start].start, tokens[end - 1].end


def surface(text: str, tokens: Sequence[Token], start: int, end: int) -> str:
    char_start, char_end = char_span(tokens, start, end)
    return text[char_start:char_end]
