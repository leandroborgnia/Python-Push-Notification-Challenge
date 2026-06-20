from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LivenessCompletion(Base):
    """Completion record written by the smoke-check task (sync) and read by the check (async).

    Shared ORM model — used by both engines; engines/sessions are NOT shared.
    """

    __tablename__ = "liveness_completion"
    __table_args__ = (
        UniqueConstraint("correlation_id", "pool_label", name="uq_liveness_completion_corr_pool"),
        CheckConstraint("pool_label IN ('cpu','io')", name="ck_liveness_completion_pool"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), index=True)
    pool_label: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
