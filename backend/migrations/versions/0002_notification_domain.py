"""notification domain (auth, contacts, templates, dispatch/delivery lifecycle)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-22

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "user_account",
        _uuid_pk(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _created_at(),
    )
    # Case-insensitive uniqueness without citext (so Base.metadata.create_all works in tests).
    op.create_index(
        "uq_user_account_email_lower",
        "user_account",
        [sa.text("lower(email)")],
        unique=True,
    )

    op.create_table(
        "email_token",
        _uuid_pk(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('verify','reset')", name="ck_email_token_purpose"),
    )
    op.create_index("ix_email_token_user_id", "email_token", ["user_id"])

    op.create_table(
        "contact",
        _uuid_pk(),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("device_token", sa.Text(), nullable=True),
        _created_at(),
    )
    op.create_index("ix_contact_owner_id", "contact", ["owner_id"])

    op.create_table(
        "template",
        _uuid_pk(),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("channel IN ('email','sms','push')", name="ck_template_channel"),
        sa.CheckConstraint(
            "channel <> 'sms' OR char_length(content) <= 160", name="ck_template_sms_length"
        ),
    )
    op.create_index("ix_template_owner_id", "template", ["owner_id"])

    op.create_table(
        "template_recipient",
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contact.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "dispatch",
        _uuid_pk(),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint("channel IN ('email','sms','push')", name="ck_dispatch_channel"),
    )
    op.create_index("ix_dispatch_user_id", "dispatch", ["user_id"])

    op.create_table(
        "delivery",
        _uuid_pk(),
        sa.Column(
            "dispatch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dispatch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contact.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued','sent','delivered','failed')", name="ck_delivery_status"
        ),
    )
    op.create_index("ix_delivery_dispatch_id", "delivery", ["dispatch_id"])
    op.create_index("ix_delivery_provider_ref", "delivery", ["provider_ref"])

    op.create_table(
        "delivery_transition",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "delivery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_delivery_transition_delivery_id", "delivery_transition", ["delivery_id"])

    op.create_table(
        "idempotency_key",
        _uuid_pk(),
        sa.Column(
            "delivery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("key", name="uq_idempotency_key_key"),
        sa.UniqueConstraint("delivery_id", name="uq_idempotency_key_delivery"),
    )
    op.create_index("ix_idempotency_key_delivery_id", "idempotency_key", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_key_delivery_id", table_name="idempotency_key")
    op.drop_table("idempotency_key")
    op.drop_index("ix_delivery_transition_delivery_id", table_name="delivery_transition")
    op.drop_table("delivery_transition")
    op.drop_index("ix_delivery_provider_ref", table_name="delivery")
    op.drop_index("ix_delivery_dispatch_id", table_name="delivery")
    op.drop_table("delivery")
    op.drop_index("ix_dispatch_user_id", table_name="dispatch")
    op.drop_table("dispatch")
    op.drop_table("template_recipient")
    op.drop_index("ix_template_owner_id", table_name="template")
    op.drop_table("template")
    op.drop_index("ix_contact_owner_id", table_name="contact")
    op.drop_table("contact")
    op.drop_index("ix_email_token_user_id", table_name="email_token")
    op.drop_table("email_token")
    op.drop_index("uq_user_account_email_lower", table_name="user_account")
    op.drop_table("user_account")
