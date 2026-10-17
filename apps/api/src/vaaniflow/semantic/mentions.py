"""Compiler-internal mention model. Never exposed outside the semantic package."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from vaaniflow.domain.schemas.semantic import TemporalExpression


class MentionKind(StrEnum):
    QUANTITY = "QUANTITY"
    BARE_NUMBER = "BARE_NUMBER"
    PRICE = "PRICE"
    PRODUCT = "PRODUCT"
    CUSTOMER = "CUSTOMER"
    TEMPORAL = "TEMPORAL"


@dataclass(slots=True)
class Mention:
    kind: MentionKind
    start: int
    end: int
    surface: str
    normalized: str
    confidence: float
    char_start: int
    char_end: int
    value: Decimal | None = None
    unit: str | None = None
    currency: str | None = None
    per_unit: str | None = None
    temporal: TemporalExpression | None = None
    mention_id: UUID = field(default_factory=uuid4)

    @property
    def is_numeric(self) -> bool:
        return self.kind in (MentionKind.QUANTITY, MentionKind.BARE_NUMBER, MentionKind.PRICE)

    def tokens(self) -> range:
        return range(self.start, self.end)
