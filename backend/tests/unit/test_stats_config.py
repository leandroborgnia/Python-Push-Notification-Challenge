from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import ValidationError
from app.domain.stats import (
    DEFAULT_INTERVAL_SECONDS,
    DISABLED,
    MIN_INTERVAL_SECONDS,
    StatsReportConfig,
)

_NOW = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def _config(interval: int, *, anchor: datetime = _NOW) -> StatsReportConfig:
    return StatsReportConfig(interval_seconds=interval, anchor_at=anchor)


@pytest.mark.parametrize(
    "seconds", [DISABLED, MIN_INTERVAL_SECONDS, DEFAULT_INTERVAL_SECONDS, 100_000]
)
def test_validate_interval_accepts_zero_and_at_or_above_minimum(seconds: int) -> None:
    StatsReportConfig.validate_interval(seconds)  # does not raise


@pytest.mark.parametrize("seconds", [1, 60, 3600, MIN_INTERVAL_SECONDS - 1])
def test_validate_interval_rejects_below_minimum(seconds: int) -> None:
    with pytest.raises(ValidationError):
        StatsReportConfig.validate_interval(seconds)


def test_with_interval_validates_and_resets_anchor() -> None:
    config = _config(DEFAULT_INTERVAL_SECONDS, anchor=_NOW - timedelta(days=10))
    later = _NOW + timedelta(hours=3)

    updated = config.with_interval(MIN_INTERVAL_SECONDS, later)

    assert updated.interval_seconds == MIN_INTERVAL_SECONDS
    assert updated.anchor_at == later  # anchor reset to the change time (FR-010)


def test_with_interval_rejects_below_minimum_and_leaves_caller_to_keep_old() -> None:
    config = _config(DEFAULT_INTERVAL_SECONDS)
    with pytest.raises(ValidationError):
        config.with_interval(3600, _NOW)


def test_is_enabled_reflects_interval() -> None:
    assert _config(DEFAULT_INTERVAL_SECONDS).is_enabled is True
    assert _config(DISABLED).is_enabled is False


def test_next_run_at_and_is_due_when_enabled() -> None:
    config = _config(MIN_INTERVAL_SECONDS)
    expected = _NOW + timedelta(seconds=MIN_INTERVAL_SECONDS)

    assert config.next_run_at() == expected
    assert config.is_due(expected - timedelta(seconds=1)) is False
    assert config.is_due(expected) is True
    assert config.is_due(expected + timedelta(days=1)) is True


def test_disabled_config_never_runs() -> None:
    config = _config(DISABLED)
    assert config.next_run_at() is None
    assert config.is_due(_NOW + timedelta(days=3650)) is False
