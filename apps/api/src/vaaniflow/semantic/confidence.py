"""
Rule-tier confidence for the deterministic compiler.

These scores are ordinal: they rank how strong the linguistic evidence
behind an extraction is (explicit digits vs. parsed number words, a name
anchored by a business suffix vs. a bare word sequence, ...). They are not
calibrated probabilities and are always tagged ``ConfidenceSource.RULE``.
Input Evaluation treats anything below ``LOW_CONFIDENCE_THRESHOLD`` on a
critical slot as requiring clarification.
"""

from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource

LOW_CONFIDENCE_THRESHOLD = 0.5

# Numbers
DIGITS = 0.95
NUMBER_WORDS = 0.85
UNIT_INHERITED = 0.8

# Names
CUSTOMER_WITH_BUSINESS_SUFFIX = 0.9
CUSTOMER_CAPITALISED = 0.8
CUSTOMER_LOWERCASE = 0.6
CUSTOMER_ADDRESSEE_OVERLAP = 0.4
ADDRESSEE_AFTER_INTERJECTION = 0.85
ADDRESSEE_LEADING_NAME = 0.65

# Products
PRODUCT_WITH_CATEGORY_NOUN = 0.9
PRODUCT_POSITIONAL_ONLY = 0.55

# Prices
PRICE_WITH_CURRENCY_AND_UNIT = 0.95
PRICE_WITH_ONE_MARKER = 0.85
PRICE_CUE_ONLY = 0.75

# Actions
ACTION_EXPLICIT = 0.9
ACTION_GENERIC_VERB = 0.7
INTENT_CONFLICT = 0.45
INTENT_NONE = 0.2

# References / temporal / corrections / tax
REFERENCE_PHRASE = 0.9
REFERENCE_PRONOUN = 0.7
TEMPORAL_LEXICAL = 0.95
TEMPORAL_TENSE_INFERRED = 0.85
TEMPORAL_AMBIGUOUS = 0.5
EXPLICIT_DATE_FULL = 0.95
EXPLICIT_DATE_PARTIAL = 0.85
EXPLICIT_DATE_NUMERIC = 0.8
CORRECTION_ADJACENT = 0.9
CORRECTION_INFERRED = 0.75
TAX_EXPLICIT = 0.95
TAX_BARE = 0.7


def rule(score: float) -> Confidence:
    return Confidence(score=score, source=ConfidenceSource.RULE)
