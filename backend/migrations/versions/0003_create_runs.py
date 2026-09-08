"""create runs

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("object_name", sa.String(), nullable=False),
        sa.Column("document_name", sa.String(), nullable=False),
        sa.Column("document_format", sa.String(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("node_hint", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("artifact_prefix", sa.String(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    op.create_index("ix_runs_thread_id", "runs", ["thread_id"])
    op.create_index("ix_runs_status", "runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_thread_id", table_name="runs")
    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_table("runs")
