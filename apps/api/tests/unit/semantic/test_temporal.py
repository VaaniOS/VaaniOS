from vaaniflow.domain.schemas.semantic import TemporalResolutionStatus
from vaaniflow.semantic.temporal import extract_temporal_expressions


def test_extracts_tomorrow_without_resolving_business_date() -> None:
    expressions = extract_temporal_expressions(
        "Dispatch it tomorrow."
    )

    assert len(expressions) == 1

    expression = expressions[0]

    assert expression.surface_text == "tomorrow"
    assert expression.normalized_expression == "DAY_OFFSET:+1"
    assert expression.resolution_status is TemporalResolutionStatus.UNRESOLVED
    assert expression.resolved_datetime is None


def test_parso_is_preserved_as_ambiguous_relative_expression() -> None:
    expressions = extract_temporal_expressions(
        "Use the rate from parso."
    )

    assert len(expressions) == 1

    expression = expressions[0]

    assert expression.surface_text == "parso"
    assert expression.resolution_status is TemporalResolutionStatus.AMBIGUOUS
    assert expression.resolved_datetime is None


def test_kal_is_not_silently_resolved() -> None:
    expressions = extract_temporal_expressions(
        "Dispatch it kal."
    )

    assert len(expressions) == 1
    assert expressions[0].resolution_status is TemporalResolutionStatus.AMBIGUOUS