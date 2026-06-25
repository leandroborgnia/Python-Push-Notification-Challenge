from __future__ import annotations

from enum import StrEnum


class Channel(StrEnum):
    """Notification channel — string values match the DB ``CHECK`` (email/sms/push), FR-016."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    REPORT = "report"  # server-originated stats-report email (004)
