"""Add missing run count to canonical meetings.

Revision ID: 002_missing_run_count
Revises: 001_initial
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op

revision = "002_missing_run_count"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "canonical_meetings",
        sa.Column("missing_run_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("canonical_meetings", "missing_run_count", server_default=None)


def downgrade() -> None:
    op.drop_column("canonical_meetings", "missing_run_count")
