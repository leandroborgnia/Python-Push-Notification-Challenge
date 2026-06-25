"""admin account, stats-report config singleton, and server-originated dispatch deltas

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22

Adds ``user_account.is_admin``; creates the singleton ``stats_report_config`` table and seeds its
one row (30 d, enabled); extends ``dispatch`` for server-originated report sends (nullable
``user_id``, ``attachment_png``, ``'report'`` channel); and idempotently seeds the single admin
from settings (env), argon2-hashed and pre-verified.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Admin designation on the existing account table (backfills existing rows to false).
    op.add_column(
        "user_account",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # 2. The singleton stats-report cadence table + its one seeded row (FR-009: 30 d, enabled).
    op.create_table(
        "stats_report_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column(
            "interval_seconds", sa.Integer(), server_default=sa.text("2592000"), nullable=False
        ),
        sa.Column(
            "anchor_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_stats_report_config_singleton"),
        sa.CheckConstraint(
            "interval_seconds = 0 OR interval_seconds >= 86400",
            name="ck_stats_report_config_interval",
        ),
    )
    op.execute(
        "INSERT INTO stats_report_config (id, interval_seconds, anchor_at, updated_at) "
        "VALUES (1, 2592000, now(), now())"
    )

    # 3. Dispatch deltas for server-originated report sends (user_id NULL ⇒ server-owned).
    op.alter_column(
        "dispatch", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.add_column("dispatch", sa.Column("attachment_png", sa.LargeBinary(), nullable=True))
    op.drop_constraint("ck_dispatch_channel", "dispatch", type_="check")
    op.create_check_constraint(
        "ck_dispatch_channel", "dispatch", "channel IN ('email','sms','push','report')"
    )

    # 4. Seed the single admin from settings (env). Idempotent on the lower(email) unique index;
    #    the password is argon2-hashed with the project hasher. The settings validator refuses the
    #    dev placeholder outside dev, so a missing prod ADMIN_PASSWORD fails the migrate Job loudly.
    from app.adapters.security.hasher import Argon2PasswordHasher
    from app.settings import get_settings

    settings = get_settings()
    password_hash = Argon2PasswordHasher().hash(settings.admin_password)
    op.get_bind().execute(
        sa.text(
            "INSERT INTO user_account (email, password_hash, is_verified, is_admin) "
            "VALUES (lower(:email), :password_hash, true, true) "
            "ON CONFLICT (lower(email)) DO NOTHING"
        ),
        {"email": settings.admin_email, "password_hash": password_hash},
    )


def downgrade() -> None:
    from app.settings import get_settings

    settings = get_settings()
    op.get_bind().execute(
        sa.text("DELETE FROM user_account WHERE lower(email) = lower(:email) AND is_admin"),
        {"email": settings.admin_email},
    )

    op.drop_constraint("ck_dispatch_channel", "dispatch", type_="check")
    op.create_check_constraint(
        "ck_dispatch_channel", "dispatch", "channel IN ('email','sms','push')"
    )
    op.drop_column("dispatch", "attachment_png")
    op.alter_column(
        "dispatch", "user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )

    op.drop_table("stats_report_config")
    op.drop_column("user_account", "is_admin")
