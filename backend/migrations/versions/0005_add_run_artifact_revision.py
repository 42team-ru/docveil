"""add run artifact revision

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("artifact_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("runs", "artifact_revision", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "artifact_revision")
