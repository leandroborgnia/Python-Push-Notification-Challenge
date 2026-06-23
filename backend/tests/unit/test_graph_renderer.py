from __future__ import annotations

import pytest

from app.adapters.graphing.matplotlib_renderer import MatplotlibGraphRenderer
from app.domain.errors import ValidationError

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_returns_non_empty_png() -> None:
    renderer = MatplotlibGraphRenderer()
    counts = list(range(24))  # 0..23

    png = renderer.render_hour_histogram(counts, title="Test scope")

    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 100


def test_render_all_zero_still_valid_png() -> None:
    png = MatplotlibGraphRenderer().render_hour_histogram([0] * 24, title="Zero")
    assert png.startswith(_PNG_MAGIC)


@pytest.mark.parametrize("counts", [[], [0] * 23, [0] * 25])
def test_render_rejects_non_length_24(counts: list[int]) -> None:
    with pytest.raises(ValidationError):
        MatplotlibGraphRenderer().render_hour_histogram(counts, title="bad")
