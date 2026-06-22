from __future__ import annotations

from typing import Protocol


class Mailer(Protocol):
    """Sends auth emails over a real, direct SMTP path (NOT the simulated notification channels).

    Awaited from the request path; never routed through Celery (research §3).
    """

    async def send_verification(self, email: str, token: str) -> None: ...

    async def send_reset(self, email: str, token: str) -> None: ...
