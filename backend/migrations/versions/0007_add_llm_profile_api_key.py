"""add llm profile api_key

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_profiles", sa.Column("api_key", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_profiles", "api_key")
