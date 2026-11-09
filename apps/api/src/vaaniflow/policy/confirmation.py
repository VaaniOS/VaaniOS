"""
Deterministic classification of a reply to a bound confirmation prompt (P2-C).

The reply is only ever interpreted as an answer to one specific pending
confirmation of one run. Anything that is not clearly a yes or clearly a no
is UNCLEAR and changes nothing; a mixed reply ("haan, mat karo") is UNCLEAR.
"""

from __future__ import annotations

import re
from enum import StrEnum


class ReplyIntent(StrEnum):
    AFFIRM = "AFFIRM"
    DECLINE = "DECLINE"
    UNCLEAR = "UNCLEAR"


_AFFIRM_WORDS = frozenset(
    {"yes", "yeah", "yep", "confirm", "confirmed", "ok", "okay", "proceed", "haan", "han", "ji"}
)
_AFFIRM_PHRASES = ("theek hai", "thik hai", "sahi hai", "go ahead", "kar do", "kardo")
_DECLINE_WORDS = frozenset(
    {"no", "nope", "nahi", "nahin", "na", "mat", "cancel", "stop", "ruko", "dont", "don't", "not"}
)


def classify_reply(text: str) -> ReplyIntent:
    normalized = " ".join(re.findall(r"[a-z']+", text.lower()))
    words = set(normalized.split())
    affirm = bool(words & _AFFIRM_WORDS) or any(p in normalized for p in _AFFIRM_PHRASES)
    decline = bool(words & _DECLINE_WORDS)
    if affirm and not decline:
        return ReplyIntent.AFFIRM
    if decline and not affirm:
        return ReplyIntent.DECLINE
    return ReplyIntent.UNCLEAR
