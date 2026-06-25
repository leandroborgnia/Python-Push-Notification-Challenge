from __future__ import annotations

import pytest

from app.domain.errors import ValidationError
from app.domain.stats import HourHistogram


def test_from_hour_counts_fills_24_buckets_missing_zero() -> None:
    histogram = HourHistogram.from_hour_counts({9: 2, 14: 1, 23: 5})

    assert len(histogram.counts) == 24
    assert histogram.counts[9] == 2
    assert histogram.counts[14] == 1
    assert histogram.counts[23] == 5
    assert histogram.counts[0] == 0  # missing hour → 0
    assert histogram.counts[13] == 0


def test_total_sums_all_buckets() -> None:
    assert HourHistogram.from_hour_counts({9: 2, 14: 1, 23: 5}).total == 8


def test_empty_scope_is_all_zeros() -> None:
    histogram = HourHistogram.from_hour_counts({})

    assert histogram.counts == tuple([0] * 24)
    assert histogram.total == 0


def test_wrong_length_rejected() -> None:
    with pytest.raises(ValidationError):
        HourHistogram(counts=(0, 1, 2))
