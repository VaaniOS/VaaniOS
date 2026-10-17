"""Temporal expressions are normalised linguistically, never resolved to dates."""

from __future__ import annotations

import pytest

from vaaniflow.domain.schemas.semantic import (
    TemporalDirection,
    TemporalExpression,
    TemporalKind,
    TemporalResolutionStatus,
    Weekday,
)
from vaaniflow.semantic.temporal import extract_temporal_expressions


def _one(text: str) -> TemporalExpression:
    expressions = extract_temporal_expressions(text)
    assert len(expressions) == 1, expressions
    return expressions[0]


@pytest.mark.parametrize(
    ("text", "surface", "offset", "direction"),
    [
        ("Dispatch it today.", "today", 0, TemporalDirection.PRESENT),
        ("Dispatch it tomorrow.", "tomorrow", 1, TemporalDirection.FUTURE),
        ("We quoted it yesterday.", "yesterday", -1, TemporalDirection.PAST),
        ("Dispatch it day after tomorrow.", "day after tomorrow", 2, TemporalDirection.FUTURE),
        ("Quoted day before yesterday.", "day before yesterday", -2, TemporalDirection.PAST),
        ("Aaj bhejo.", "Aaj", 0, TemporalDirection.PRESENT),
    ],
)
def test_lexical_relative_days(
    text: str,
    surface: str,
    offset: int,
    direction: TemporalDirection,
) -> None:
    expression = _one(text)

    assert expression.surface_text == surface
    assert expression.kind is TemporalKind.RELATIVE_DAY
    assert expression.day_offset == offset
    assert expression.direction is direction
    assert expression.normalized_expression == f"DAY_OFFSET:{offset:+d}"
    assert expression.resolution_status is TemporalResolutionStatus.UNRESOLVED
    assert expression.day is None and expression.month is None  # never a calendar date


def test_day_after_tomorrow_is_one_expression_not_two() -> None:
    expressions = extract_temporal_expressions("Dispatch day after tomorrow, not tomorrow.")

    assert [(e.surface_text, e.day_offset) for e in expressions] == [
        ("day after tomorrow", 2),
        ("tomorrow", 1),
    ]


@pytest.mark.parametrize(
    ("text", "offset", "evidence"),
    [
        ("Rate wahi jo parso bataya tha.", -2, "past-tense cue 'bataya'"),
        ("Parso dispatch karo.", 2, "future/imperative cue 'karo'"),
        ("Kal bola tha.", -1, "past-tense cue 'bola'"),
        ("Kal dispatch karo.", 1, "future/imperative cue 'karo'"),
    ],
)
def test_bidirectional_hindi_day_words_follow_tense(text: str, offset: int, evidence: str) -> None:
    expression = _one(text)

    assert expression.day_offset == offset
    assert expression.direction_evidence == evidence
    assert expression.resolution_status is TemporalResolutionStatus.UNRESOLVED


def test_narso_is_three_days_and_follows_tense() -> None:
    future = _one("Narso dispatch karo.")
    past = _one("Narso bataya tha.")

    assert (future.surface_text, future.day_offset, future.normalized_expression) == (
        "Narso",
        3,
        "DAY_OFFSET:+3",
    )
    assert future.direction is TemporalDirection.FUTURE
    assert (past.day_offset, past.direction) == (-3, TemporalDirection.PAST)


def test_narso_without_tense_is_ambiguous() -> None:
    expression = _one("Narso.")

    assert expression.resolution_status is TemporalResolutionStatus.AMBIGUOUS
    assert expression.normalized_expression == "DAY_OFFSET:±3"


@pytest.mark.parametrize("text", ["Parso.", "Sharma Builders, kal."])
def test_bidirectional_day_word_without_tense_is_ambiguous(text: str) -> None:
    expression = _one(text)

    assert expression.resolution_status is TemporalResolutionStatus.AMBIGUOUS
    assert expression.direction is TemporalDirection.UNKNOWN
    assert expression.day_offset is None
    assert expression.normalized_expression.startswith("DAY_OFFSET:±")


def test_words_containing_kal_are_not_temporal() -> None:
    assert extract_temporal_expressions("Dispatch to Kalyan Traders.") == []


@pytest.mark.parametrize(
    ("text", "day", "month", "year", "status"),
    [
        ("Deliver on 25 October 2026.", 25, 10, 2026, TemporalResolutionStatus.ABSOLUTE),
        ("Deliver on 25th Oct.", 25, 10, None, TemporalResolutionStatus.UNRESOLVED),
        ("Deliver on October 25, 2026.", 25, 10, 2026, TemporalResolutionStatus.ABSOLUTE),
        ("Deliver on 25/10/2026.", 25, 10, 2026, TemporalResolutionStatus.ABSOLUTE),
        ("Deliver on 2026-10-25.", 25, 10, 2026, TemporalResolutionStatus.ABSOLUTE),
        ("Deliver on 25/10.", 25, 10, None, TemporalResolutionStatus.UNRESOLVED),
    ],
)
def test_explicit_dates(
    text: str,
    day: int,
    month: int,
    year: int | None,
    status: TemporalResolutionStatus,
) -> None:
    expression = _one(text)

    assert expression.kind is TemporalKind.EXPLICIT_DATE
    assert (expression.day, expression.month, expression.year) == (day, month, year)
    assert expression.resolution_status is status


@pytest.mark.parametrize("text", ["Deliver on 31/02/2026.", "Deliver on 45 October."])
def test_invalid_dates_are_not_extracted(text: str) -> None:
    assert extract_temporal_expressions(text) == []


@pytest.mark.parametrize(
    ("text", "weekday", "week_offset", "direction"),
    [
        ("Deliver next Friday.", Weekday.FRIDAY, 1, TemporalDirection.FUTURE),
        ("Quoted last Monday.", Weekday.MONDAY, -1, TemporalDirection.PAST),
        ("Deliver on Friday.", Weekday.FRIDAY, None, TemporalDirection.FUTURE),
        ("Shukravar ko bhejo.", Weekday.FRIDAY, None, TemporalDirection.FUTURE),
        ("Agle somvar dispatch karo.", Weekday.MONDAY, 1, TemporalDirection.FUTURE),
    ],
)
def test_days_of_week(
    text: str,
    weekday: Weekday,
    week_offset: int | None,
    direction: TemporalDirection,
) -> None:
    expression = _one(text)

    assert expression.kind is TemporalKind.WEEKDAY
    assert expression.weekday is weekday
    assert expression.week_offset == week_offset
    assert expression.direction is direction
    assert expression.resolution_status is TemporalResolutionStatus.UNRESOLVED


@pytest.mark.parametrize(
    ("text", "offset"),
    [("Deliver next week.", 1), ("Pichhle hafte ka rate.", -1), ("Is hafte bhejo.", 0)],
)
def test_relative_weeks(text: str, offset: int) -> None:
    expression = _one(text)

    assert expression.kind is TemporalKind.RELATIVE_WEEK
    assert expression.week_offset == offset


def test_dates_are_not_mistaken_for_quantities() -> None:
    from .conftest import compile_text

    state = compile_text("Deliver 100 bags ACC cement to Kumar Constructions on 25 October 2026.")

    assert [(i.quantity.value, i.quantity.unit) for i in state.items if i.quantity] == [
        (100, "bag")
    ]
    assert state.temporal_expressions[0].target.value == "EXECUTION"
