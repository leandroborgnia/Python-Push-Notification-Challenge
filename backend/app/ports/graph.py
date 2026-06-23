from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class GraphRenderer(Protocol):
    """Isolates the plotting library behind a port so ``application/`` never imports matplotlib."""

    def render_hour_histogram(self, counts: Sequence[int], *, title: str) -> bytes:
        """Render a 24-bar bar chart (x = UTC hour 00..23, y = count) to PNG bytes.

        ``counts`` MUST have length 24. Returns non-empty PNG bytes (``\\x89PNG`` header).
        """
        ...
