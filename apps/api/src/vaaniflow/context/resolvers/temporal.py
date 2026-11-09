from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from vaaniflow.context.models.resolution import (
    ResolutionCandidate,
    ResolutionResult,
    ResolutionStatus,
)
from vaaniflow.domain.schemas.common import Confidence, ConfidenceSource
from vaaniflow.domain.schemas.semantic import TemporalExpression


class TemporalResolver:
    """
    Deterministic relative date resolver.

    Normalizes expressions like 'parso', 'kal', 'aaj' into exact calendar dates
    using the business timezone and run timestamp.
    """

    def __init__(self, timezone_str: str = "Asia/Kolkata") -> None:
        self._tz = ZoneInfo(timezone_str)
        self._timezone_str = timezone_str

    def business_date(self, timestamp: datetime) -> date:
        """Calendar date of ``timestamp`` in the business timezone."""
        return timestamp.astimezone(self._tz).date()

    def resolve(
        self,
        *,
        expression: TemporalExpression,
        run_timestamp: datetime,
    ) -> tuple[ResolutionResult, date | None]:
        resolution_id = uuid4()
        query = expression.surface_text

        # Base date in the business timezone
        local_now = run_timestamp.astimezone(self._tz)
        base_date = local_now.date()

        if expression.day_offset is None:
            return (
                ResolutionResult(
                    resolution_id=resolution_id,
                    entity_type="date",
                    status=ResolutionStatus.INVALID,
                    query=query,
                    selected_entity_id=None,
                    candidates=[],
                    reason=f"Temporal expression '{query}' has no computable day offset.",
                ),
                None,
            )

        resolved_date = base_date + timedelta(days=expression.day_offset)

        candidate = ResolutionCandidate(
            candidate_id=uuid4(),
            entity_id=uuid4(),
            display_name=resolved_date.isoformat(),
            confidence=Confidence(
                score=0.99,
                source=ConfidenceSource.RULE,
            ),
            evidence=[
                f"Relative offset {expression.day_offset} days from base date {base_date} ({self._timezone_str})"
            ],
            attributes={
                "base_date": base_date.isoformat(),
                "resolved_date": resolved_date.isoformat(),
                "timezone": self._timezone_str,
                "surface_text": query,
            },
        )

        return (
            ResolutionResult(
                resolution_id=resolution_id,
                entity_type="date",
                status=ResolutionStatus.RESOLVED,
                query=query,
                selected_entity_id=candidate.entity_id,
                candidates=[candidate],
                reason=f"Resolved '{query}' to calendar date {resolved_date.isoformat()} in {self._timezone_str}.",
            ),
            resolved_date,
        )
