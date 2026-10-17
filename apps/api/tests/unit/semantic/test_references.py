from vaaniflow.domain.schemas.semantic import ReferenceType
from vaaniflow.semantic.references import extract_references


def test_extracts_historical_price_reference() -> None:
    references = extract_references(
        "Use the same rate we discussed earlier."
    )

    assert any(
        reference.reference_type is ReferenceType.HISTORICAL_PRICE
        for reference in references
    )


def test_extracts_customer_reference() -> None:
    references = extract_references(
        "Send it to the same customer."
    )

    assert any(
        reference.reference_type is ReferenceType.CUSTOMER
        for reference in references
    )


def test_extracts_previous_quote_reference() -> None:
    references = extract_references(
        "Use the previous quote."
    )

    assert any(
        reference.reference_type is ReferenceType.HISTORICAL_QUOTE
        for reference in references
    )