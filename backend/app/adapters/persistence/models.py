from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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


# --- 003 notification domain (shared by the async API engine and the sync Celery engine) ----------


class UserAccount(Base):
    """A registered user. Email is stored lowercased; uniqueness is case-insensitive via the
    functional unique index ``lower(email)`` (no ``citext`` so ``create_all`` works in tests)."""

    __tablename__ = "user_account"
    __table_args__ = (Index("uq_user_account_email_lower", text("lower(email)"), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailToken(Base):
    """Single-use opaque token (hashed at rest) for email verification and password reset."""

    __tablename__ = "email_token"
    __table_args__ = (
        CheckConstraint("purpose IN ('verify','reset')", name="ck_email_token_purpose"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Contact(Base):
    """A private contact in a user's personal book (add + list only this version)."""

    __tablename__ = "contact"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    """A reusable per-user notification definition; editing never sends (FR-017)."""

    __tablename__ = "template"
    __table_args__ = (
        CheckConstraint("channel IN ('email','sms','push')", name="ck_template_channel"),
        CheckConstraint(
            "channel <> 'sms' OR char_length(content) <= 160", name="ck_template_sms_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TemplateRecipient(Base):
    """Association: a template's stored recipient set (composite PK)."""

    __tablename__ = "template_recipient"

    template_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("template.id", ondelete="CASCADE"),
        primary_key=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("contact.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Dispatch(Base):
    """The send snapshot. Holds NO foreign key to ``template`` (FR-030) so later template edits
    never alter a past send.

    ``user_id`` is nullable: ``NULL`` marks a **server-originated** send (a stats report), excluded
    from aggregation and from every user's send-history (both key off ``user_id``). FR-020.
    """

    __tablename__ = "dispatch"
    __table_args__ = (
        CheckConstraint("channel IN ('email','sms','push','report')", name="ck_dispatch_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    attachment_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Delivery(Base):
    """A per-recipient send record with a persisted lifecycle (current status here; full history in
    ``delivery_transition``)."""

    __tablename__ = "delivery"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','sent','delivered','failed')", name="ck_delivery_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    dispatch_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("dispatch.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("contact.id", ondelete="SET NULL"), nullable=True
    )
    recipient_name: Mapped[str] = mapped_column(Text)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"), default="queued")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DeliveryTransition(Base):
    """Append-only lifecycle history — never updated or deleted (Principle IV, FR-025)."""

    __tablename__ = "delivery_transition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("delivery.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyKey(Base):
    """Hand-rolled dedupe claim: one row per (dispatch, recipient); a unique-violation on insert
    means a retry already delivered, so no second send (FR-024/FR-026, SC-007)."""

    __tablename__ = "idempotency_key"
    __table_args__ = (
        UniqueConstraint("key", name="uq_idempotency_key_key"),
        UniqueConstraint("delivery_id", name="uq_idempotency_key_delivery"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("delivery.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- 004 admin stats-report (singleton cadence + scheduling anchor) -------------------------------


class StatsReportConfig(Base):
    """The single, server-wide report cadence row. The ``id = 1`` CHECK makes it a true singleton;
    ``interval_seconds = 0`` disables reporting, ``>= 86400`` enables it (defence-in-depth CHECK
    behind the API validation). ``anchor_at`` drives due-ness (next_run = anchor + interval)."""

    __tablename__ = "stats_report_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_stats_report_config_singleton"),
        CheckConstraint(
            "interval_seconds = 0 OR interval_seconds >= 86400",
            name="ck_stats_report_config_interval",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    interval_seconds: Mapped[int] = mapped_column(
        Integer, server_default=text("2592000"), default=2592000
    )
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
