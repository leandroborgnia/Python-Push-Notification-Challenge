"""create liveness_completion

Revision ID: 0001
Revises:
Create Date: 2026-06-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "liveness_completion",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pool_label", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "correlation_id", "pool_label", name="uq_liveness_completion_corr_pool"
        ),
        sa.CheckConstraint("pool_label IN ('cpu','io')", name="ck_liveness_completion_pool"),
    )
    op.create_index(
        "ix_liveness_completion_correlation_id",
        "liveness_completion",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_liveness_completion_correlation_id", table_name="liveness_completion")
    op.drop_table("liveness_completion")
