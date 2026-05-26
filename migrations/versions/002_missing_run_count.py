"""Add missing run count to canonical meetings.

Revision ID: 002_missing_run_count
Revises: 001_initial
Create Date: 2026-04-30
"""

from alembic import op

revision = "002_missing_run_count"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE canonical_meetings "
        "ADD COLUMN IF NOT EXISTS missing_run_count INT NOT NULL DEFAULT 0"
    )
    op.alter_column("canonical_meetings", "missing_run_count", server_default=None)


def downgrade() -> None:
    op.drop_column("canonical_meetings", "missing_run_count")
