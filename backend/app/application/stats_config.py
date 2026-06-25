from __future__ import annotations

from dataclasses import dataclass

from app.domain.stats import DISABLED, StatsReportConfig
from app.ports.clock import Clock
from app.ports.repositories import StatsConfigRepository


@dataclass(frozen=True, slots=True)
class FrequencyView:
    """The admin-facing view of the report cadence (maps 1:1 to the API response)."""

    interval_seconds: int
    enabled: bool

    @staticmethod
    def of(interval_seconds: int) -> FrequencyView:
        return FrequencyView(
            interval_seconds=interval_seconds, enabled=interval_seconds != DISABLED
        )


class StatsConfigService:
    """Read/update the single server-wide report frequency (US1, async API path)."""

    def __init__(self, *, repository: StatsConfigRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def get_frequency(self) -> FrequencyView:
        config = await self._repository.get()
        return FrequencyView.of(config.interval_seconds)

    async def set_frequency(self, interval_seconds: int) -> FrequencyView:
        """Validate (domain → 422 on 1..86_399), persist, and reset the scheduling anchor (FR-010).

        ``0`` disables reporting; a below-minimum value is rejected and the stored value is left
        unchanged (the validation raises before any write)."""
        StatsReportConfig.validate_interval(interval_seconds)
        await self._repository.set_interval(interval_seconds, self._clock.now())
        return FrequencyView.of(interval_seconds)
