"""make experiment correct nullable

Revision ID: a1b2c3d4e5f6
Revises: 6e43f105de6a
Create Date: 2026-06-09 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "6e43f105de6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "experiments", "correct", existing_type=sa.Boolean(), nullable=True, server_default=None
    )
    op.execute("UPDATE experiments SET correct = NULL")


def downgrade() -> None:
    op.execute("UPDATE experiments SET correct = TRUE WHERE correct IS NULL")
    op.alter_column(
        "experiments", "correct", existing_type=sa.Boolean(), nullable=False, server_default="true"
    )
