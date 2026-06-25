from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import matplotlib

# The headless Agg backend must be selected BEFORE importing pyplot (no display in the worker).
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow matplotlib.use)

from app.domain.errors import ValidationError  # noqa: E402
from app.domain.stats import HOURS_PER_DAY  # noqa: E402

_BAR_COLOR = "#4C72B0"


class MatplotlibGraphRenderer:
    """``GraphRenderer`` impl — a 24-bar per-UTC-hour PNG via matplotlib (Agg). CPU-bound; runs on
    the prefork ``cpu`` pool (research §5)."""

    def render_hour_histogram(self, counts: Sequence[int], *, title: str) -> bytes:
        if len(counts) != HOURS_PER_DAY:
            raise ValidationError(
                f"render_hour_histogram requires exactly {HOURS_PER_DAY} counts; got {len(counts)}"
            )
        hours = [f"{hour:02d}" for hour in range(HOURS_PER_DAY)]
        fig, ax = plt.subplots(figsize=(10, 4))
        try:
            ax.bar(hours, list(counts), color=_BAR_COLOR)
            ax.set_title(title)
            ax.set_xlabel("UTC hour")
            ax.set_ylabel("Sends reaching 'sent'")
            ax.margins(x=0.01)
            fig.tight_layout()
            buffer = BytesIO()
            fig.savefig(buffer, format="png")
        finally:
            plt.close(fig)
        return buffer.getvalue()
