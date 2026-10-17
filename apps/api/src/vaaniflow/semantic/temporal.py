"""
Temporal expression extraction (System-Design 05 §5.2, 06 §6.5, ADR-014).

The compiler normalises *what was said* ("parso" → two days, past) but
never turns it into a calendar date: that needs the run clock, the business
timezone and calendar, which belong to context resolution.

Bidirectional Hindi day words ("kal" = ±1, "parso" = ±2, "narso" = ±3) are
oriented by deterministic tense evidence in the same clause ("bataya tha" →
past, "dispatch karo" → future). Without evidence they stay AMBIGUOUS.
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import uuid4

from vaaniflow.domain.schemas.semantic import (
    TemporalDirection,
    TemporalExpression,
    TemporalKind,
    TemporalResolutionStatus,
    TemporalTarget,
    TextSpan,
    Weekday,
)
from vaaniflow.semantic import confidence as conf
from vaaniflow.semantic.lexicon import (
    FUTURE_TENSE_CUES,
    PAST_TENSE_CUES,
    WEAK_FUTURE_CUES,
)
from vaaniflow.semantic.mentions import Mention, MentionKind
from vaaniflow.semantic.text import Token, TokenKind, char_span, phrases, surface, tokenize


@dataclass(frozen=True, slots=True)
class _DayWord:
    magnitude: int
    direction: TemporalDirection | None  # None = bidirectional (needs tense)


_DAY_WORDS: dict[tuple[str, ...], _DayWord] = {
    **{p: _DayWord(2, TemporalDirection.FUTURE) for p in phrases(["day after tomorrow"])},
    **{p: _DayWord(2, TemporalDirection.PAST) for p in phrases(["day before yesterday"])},
    **{p: _DayWord(1, TemporalDirection.FUTURE) for p in phrases(["tomorrow"])},
    **{p: _DayWord(1, TemporalDirection.PAST) for p in phrases(["yesterday"])},
    **{p: _DayWord(0, TemporalDirection.PRESENT) for p in phrases(["today", "tonight", "aaj"])},
    **{p: _DayWord(1, None) for p in phrases(["kal"])},
    **{p: _DayWord(2, None) for p in phrases(["parso", "parson", "parsoon"])},
    **{p: _DayWord(3, None) for p in phrases(["narso", "narson"])},
}

_WEEK_WORDS: dict[tuple[str, ...], int] = {
    **dict.fromkeys(
        phrases(["next week", "coming week", "agle hafte", "agla hafta", "agle week"]), 1
    ),
    **dict.fromkeys(
        phrases(["last week", "previous week", "pichhle hafte", "pichle hafte", "pichla hafta"]),
        -1,
    ),
    **dict.fromkeys(phrases(["this week", "is hafte", "isi hafte"]), 0),
}

_WEEKDAYS: dict[str, Weekday] = {
    **dict.fromkeys(("monday", "somvar", "somvaar"), Weekday.MONDAY),
    **dict.fromkeys(("tuesday", "mangalvar", "mangalvaar"), Weekday.TUESDAY),
    **dict.fromkeys(("wednesday", "budhvar", "budhvaar"), Weekday.WEDNESDAY),
    **dict.fromkeys(
        ("thursday", "guruvar", "guruvaar", "brihaspativar", "veervar"), Weekday.THURSDAY
    ),
    **dict.fromkeys(("friday", "shukravar", "shukravaar"), Weekday.FRIDAY),
    **dict.fromkeys(("saturday", "shanivar", "shanivaar"), Weekday.SATURDAY),
    **dict.fromkeys(("sunday", "ravivar", "ravivaar", "itvaar"), Weekday.SUNDAY),
}

_WEEKDAY_MODIFIERS: dict[str, int] = {
    **dict.fromkeys(("next", "coming", "agle", "agla", "agli"), 1),
    **dict.fromkeys(("last", "previous", "pichhle", "pichle", "pichla", "pichhla"), -1),
    **dict.fromkeys(("this",), 0),
}

_MONTHS: dict[str, int] = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}

_ORDINAL_SUFFIXES = frozenset({"st", "nd", "rd", "th"})


def _sign(direction: TemporalDirection) -> int:
    return -1 if direction is TemporalDirection.PAST else 1


def infer_direction(
    tokens: Sequence[Token],
    start: int,
    end: int,
) -> tuple[TemporalDirection, str | None]:
    """
    Orient a bidirectional day word using tense cues in its sub-clause.

    Hindi is verb-final, so the verb group after the expression is checked
    first, then the words before it. A sub-clause ends at any punctuation.
    """
    after: list[Token] = []
    for token in tokens[end:]:
        if token.is_punct:
            break
        after.append(token)

    before: list[Token] = []
    for token in reversed(tokens[:start]):
        if token.is_punct:
            break
        before.append(token)

    for window in (after, before):
        past = [t for t in window if t.lower in PAST_TENSE_CUES]
        future = [t for t in window if t.lower in FUTURE_TENSE_CUES]

        if past and not future:
            return TemporalDirection.PAST, f"past-tense cue '{past[0].text}'"
        if future and not past:
            return TemporalDirection.FUTURE, f"future/imperative cue '{future[0].text}'"
        if past and future:
            first = min(past[0], future[0], key=lambda t: abs(t.index - start))
            if first in past:
                return TemporalDirection.PAST, f"nearest tense cue '{first.text}'"
            return TemporalDirection.FUTURE, f"nearest tense cue '{first.text}'"

        weak = [t for t in window if t.lower in WEAK_FUTURE_CUES]
        if weak:
            return TemporalDirection.FUTURE, f"action verb '{weak[0].text}'"

    return TemporalDirection.UNKNOWN, None


def _relative_day(
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    word: _DayWord,
) -> TemporalExpression:
    direction = word.direction
    evidence: str | None = None
    score = conf.TEMPORAL_LEXICAL

    if direction is None:
        direction, evidence = infer_direction(tokens, start, end)
        score = (
            conf.TEMPORAL_AMBIGUOUS
            if direction is TemporalDirection.UNKNOWN
            else conf.TEMPORAL_TENSE_INFERRED
        )

    return build_relative_day(
        text=text,
        tokens=tokens,
        start=start,
        end=end,
        magnitude=word.magnitude,
        direction=direction,
        evidence=evidence,
        score=score,
    )


def build_relative_day(
    *,
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    magnitude: int,
    direction: TemporalDirection,
    evidence: str | None,
    score: float,
) -> TemporalExpression:
    char_start, char_end = char_span(tokens, start, end)

    if direction is TemporalDirection.UNKNOWN:
        return TemporalExpression(
            expression_id=uuid4(),
            surface_text=text[char_start:char_end],
            span=TextSpan(start=char_start, end=char_end),
            kind=TemporalKind.RELATIVE_DAY,
            normalized_expression=f"DAY_OFFSET:±{magnitude}",
            direction=direction,
            resolution_status=TemporalResolutionStatus.AMBIGUOUS,
            direction_evidence=evidence,
            confidence=conf.rule(score),
        )

    offset = 0 if direction is TemporalDirection.PRESENT else _sign(direction) * magnitude
    return TemporalExpression(
        expression_id=uuid4(),
        surface_text=text[char_start:char_end],
        span=TextSpan(start=char_start, end=char_end),
        kind=TemporalKind.RELATIVE_DAY,
        normalized_expression=f"DAY_OFFSET:{offset:+d}",
        direction=direction,
        day_offset=offset,
        resolution_status=TemporalResolutionStatus.UNRESOLVED,
        direction_evidence=evidence,
        confidence=conf.rule(score),
    )


def _int_token(tokens: Sequence[Token], index: int) -> int | None:
    if index < len(tokens) and tokens[index].kind is TokenKind.NUMBER:
        raw = tokens[index].text
        if raw.isdigit():
            return int(raw)
    return None


def _valid_day(day: int, month: int, year: int | None) -> bool:
    if not 1 <= month <= 12:
        return False
    limit = calendar.monthrange(year if year is not None else 2024, month)[1]
    return 1 <= day <= limit


def _year_at(tokens: Sequence[Token], index: int) -> tuple[int | None, int]:
    position = index
    if position < len(tokens) and tokens[position].text == ",":
        position += 1
    year = _int_token(tokens, position)
    if year is not None and 1900 <= year <= 2100 and len(tokens[position].text) == 4:
        return year, position + 1
    return None, index


def _skip_ordinal(tokens: Sequence[Token], index: int) -> int:
    if index < len(tokens) and tokens[index].lower in _ORDINAL_SUFFIXES:
        return index + 1
    return index


def _match_explicit_date(
    tokens: Sequence[Token],
    index: int,
) -> tuple[int, int, int | None, int, float] | None:
    """Return (day, month, year, end, score) for a date starting at index."""
    # 15 October [2026] / 15th of Oct
    day = _int_token(tokens, index)
    if day is not None:
        position = _skip_ordinal(tokens, index + 1)
        if position < len(tokens) and tokens[position].lower == "of":
            position += 1
        if position < len(tokens) and tokens[position].lower in _MONTHS:
            month = _MONTHS[tokens[position].lower]
            year, end = _year_at(tokens, position + 1)
            if _valid_day(day, month, year):
                score = conf.EXPLICIT_DATE_FULL if year else conf.EXPLICIT_DATE_PARTIAL
                return day, month, year, end, score

        # 15/10[/2026], 15-10-2026, 2026-10-15
        if index + 2 < len(tokens) and tokens[index + 1].text in {"/", "-"}:
            separator = tokens[index + 1].text
            second = _int_token(tokens, index + 2)
            if second is not None:
                third: int | None = None
                end = index + 3
                if (
                    end + 1 < len(tokens)
                    and tokens[end].text == separator
                    and _int_token(tokens, end + 1) is not None
                ):
                    third = _int_token(tokens, end + 1)
                    end += 2
                if len(tokens[index].text) == 4 and third is not None:
                    year, month, day = day, second, third
                    if 1900 <= year <= 2100 and _valid_day(day, month, year):
                        return day, month, year, end, conf.EXPLICIT_DATE_FULL
                    return None
                year = third if third is not None and 1900 <= third <= 2100 else None
                if third is not None and year is None:
                    return None
                if _valid_day(day, second, year):
                    return day, second, year, end, conf.EXPLICIT_DATE_NUMERIC

    # October 15[th] [, 2026]
    if index < len(tokens) and tokens[index].lower in _MONTHS:
        day = _int_token(tokens, index + 1)
        if day is not None:
            month = _MONTHS[tokens[index].lower]
            position = _skip_ordinal(tokens, index + 2)
            year, end = _year_at(tokens, position)
            if _valid_day(day, month, year):
                score = conf.EXPLICIT_DATE_FULL if year else conf.EXPLICIT_DATE_PARTIAL
                return day, month, year, end, score

    return None


def _explicit_date(
    text: str,
    tokens: Sequence[Token],
    start: int,
    match: tuple[int, int, int | None, int, float],
) -> TemporalExpression:
    day, month, year, end, score = match
    char_start, char_end = char_span(tokens, start, end)
    normalized = (
        f"DATE:{year:04d}-{month:02d}-{day:02d}" if year else f"DATE:--{month:02d}-{day:02d}"
    )
    return TemporalExpression(
        expression_id=uuid4(),
        surface_text=text[char_start:char_end],
        span=TextSpan(start=char_start, end=char_end),
        kind=TemporalKind.EXPLICIT_DATE,
        normalized_expression=normalized,
        direction=TemporalDirection.UNKNOWN,
        day=day,
        month=month,
        year=year,
        resolution_status=(
            TemporalResolutionStatus.ABSOLUTE if year else TemporalResolutionStatus.UNRESOLVED
        ),
        confidence=conf.rule(score),
    )


def _weekday(
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    weekday: Weekday,
    week_offset: int | None,
) -> TemporalExpression:
    char_start, char_end = char_span(tokens, start, end)

    evidence: str | None = None
    if week_offset is None:
        direction, evidence = infer_direction(tokens, start, end)
    elif week_offset > 0:
        direction = TemporalDirection.FUTURE
    elif week_offset < 0:
        direction = TemporalDirection.PAST
    else:
        direction = TemporalDirection.UNKNOWN

    modifier = "" if week_offset is None else f";WEEK_OFFSET:{week_offset:+d}"
    return TemporalExpression(
        expression_id=uuid4(),
        surface_text=text[char_start:char_end],
        span=TextSpan(start=char_start, end=char_end),
        kind=TemporalKind.WEEKDAY,
        normalized_expression=f"WEEKDAY:{weekday.value}{modifier}",
        direction=direction,
        week_offset=week_offset,
        weekday=weekday,
        resolution_status=TemporalResolutionStatus.UNRESOLVED,
        direction_evidence=evidence,
        confidence=conf.rule(conf.TEMPORAL_LEXICAL),
    )


def _relative_week(
    text: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    offset: int,
) -> TemporalExpression:
    char_start, char_end = char_span(tokens, start, end)
    direction = (
        TemporalDirection.FUTURE
        if offset > 0
        else TemporalDirection.PAST
        if offset < 0
        else TemporalDirection.PRESENT
    )
    return TemporalExpression(
        expression_id=uuid4(),
        surface_text=text[char_start:char_end],
        span=TextSpan(start=char_start, end=char_end),
        kind=TemporalKind.RELATIVE_WEEK,
        normalized_expression=f"WEEK_OFFSET:{offset:+d}",
        direction=direction,
        week_offset=offset,
        resolution_status=TemporalResolutionStatus.UNRESOLVED,
        confidence=conf.rule(conf.TEMPORAL_LEXICAL),
    )


def _longest(
    tokens: Sequence[Token],
    index: int,
    table: Mapping[tuple[str, ...], object],
) -> tuple[str, ...] | None:
    best: tuple[str, ...] | None = None
    for words in table:
        if len(words) > (len(best) if best else 0) and all(
            index + offset < len(tokens) and tokens[index + offset].lower == word
            for offset, word in enumerate(words)
        ):
            best = words
    return best


def extract_temporal_mentions(text: str, tokens: Sequence[Token]) -> list[Mention]:
    """
    Extract temporal expressions, longest match first, never overlapping.

    "day after tomorrow" yields exactly one expression (+2), not also "+1".
    """
    mentions: list[Mention] = []
    index = 0

    while index < len(tokens):
        expression: TemporalExpression | None = None
        end = index

        date_match = _match_explicit_date(tokens, index)
        if date_match is not None:
            expression = _explicit_date(text, tokens, index, date_match)
            end = date_match[3]

        if expression is None:
            words = _longest(tokens, index, _WEEK_WORDS)
            if words is not None:
                end = index + len(words)
                expression = _relative_week(text, tokens, index, end, _WEEK_WORDS[words])

        if expression is None:
            words = _longest(tokens, index, _DAY_WORDS)
            if words is not None:
                end = index + len(words)
                expression = _relative_day(text, tokens, index, end, _DAY_WORDS[words])

        if expression is None and tokens[index].lower in _WEEKDAY_MODIFIERS:
            following = index + 1
            if following < len(tokens) and tokens[following].lower in _WEEKDAYS:
                end = following + 1
                expression = _weekday(
                    text,
                    tokens,
                    index,
                    end,
                    _WEEKDAYS[tokens[following].lower],
                    _WEEKDAY_MODIFIERS[tokens[index].lower],
                )

        if expression is None and tokens[index].lower in _WEEKDAYS:
            end = index + 1
            expression = _weekday(text, tokens, index, end, _WEEKDAYS[tokens[index].lower], None)

        if expression is None:
            index += 1
            continue

        char_start, char_end = char_span(tokens, index, end)
        mentions.append(
            Mention(
                kind=MentionKind.TEMPORAL,
                start=index,
                end=end,
                surface=surface(text, tokens, index, end),
                normalized=expression.normalized_expression,
                confidence=expression.confidence.score,
                char_start=char_start,
                char_end=char_end,
                temporal=expression,
                mention_id=expression.expression_id,
            )
        )
        index = end

    return mentions


def extract_temporal_expressions(text: str) -> list[TemporalExpression]:
    """Convenience wrapper returning only the expressions."""
    return [
        mention.temporal
        for mention in extract_temporal_mentions(text, tokenize(text))
        if mention.temporal is not None
    ]


def _updated(expression: TemporalExpression, changes: dict[str, object]) -> TemporalExpression:
    """Copy with changes, re-running schema validation (model_copy does not)."""
    return TemporalExpression.model_validate({**expression.model_dump(), **changes})


def orient(
    expression: TemporalExpression,
    direction: TemporalDirection,
    evidence: str,
) -> TemporalExpression:
    """Give a bidirectional day word / bare weekday a direction from evidence."""
    if expression.kind is TemporalKind.RELATIVE_DAY and direction in (
        TemporalDirection.PAST,
        TemporalDirection.FUTURE,
    ):
        magnitude = abs(expression.day_offset or 0) or int(
            expression.normalized_expression.rsplit("±", 1)[-1]
        )
        offset = _sign(direction) * magnitude
        return _updated(
            expression,
            {
                "normalized_expression": f"DAY_OFFSET:{offset:+d}",
                "direction": direction,
                "day_offset": offset,
                "resolution_status": TemporalResolutionStatus.UNRESOLVED,
                "direction_evidence": evidence,
                "confidence": conf.rule(conf.TEMPORAL_TENSE_INFERRED),
            },
        )
    if expression.kind is TemporalKind.WEEKDAY:
        return _updated(expression, {"direction": direction, "direction_evidence": evidence})
    return expression


def _tense_inferred(expression: TemporalExpression) -> bool:
    """True when the direction was not fixed lexically ("tomorrow" is fixed)."""
    return expression.direction is TemporalDirection.UNKNOWN or (
        expression.direction_evidence is not None
        and expression.kind in (TemporalKind.RELATIVE_DAY, TemporalKind.WEEKDAY)
    )


def anchor_to_reference(
    expression: TemporalExpression, reference_surface: str
) -> TemporalExpression:
    """
    A temporal expression qualifying a historical reference ("rate wahi jo
    parso bataya tha", "same rate as parso") points to the past by
    definition: the referenced rate/quote/order already exists.
    """
    if _tense_inferred(expression):
        expression = orient(
            expression,
            TemporalDirection.PAST,
            f"qualifies historical reference '{reference_surface}'",
        )
    return _updated(expression, {"target": TemporalTarget.REFERENCE})


def inherit_direction(
    replacement: TemporalExpression, previous: TemporalExpression
) -> TemporalExpression:
    """A corrected day word keeps the orientation of the value it replaces."""
    if replacement.direction is not TemporalDirection.UNKNOWN or previous.direction not in (
        TemporalDirection.PAST,
        TemporalDirection.FUTURE,
    ):
        return replacement
    return orient(
        replacement,
        previous.direction,
        f"inherited from corrected expression '{previous.surface_text}'",
    )
