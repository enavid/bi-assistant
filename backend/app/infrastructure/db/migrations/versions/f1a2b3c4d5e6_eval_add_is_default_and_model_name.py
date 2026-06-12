"""eval: add is_default to question sets and model_name to runs

Revision ID: f1a2b3c4d5e6
Revises: cd15cf9412d6
Create Date: 2026-06-12 16:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "cd15cf9412d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_question_sets",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "eval_runs",
        sa.Column("model_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "model_name")
    op.drop_column("eval_question_sets", "is_default")
