"""Initial ingestion schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-30
"""

from pathlib import Path

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "001_initial.sql"
    statements = [statement.strip() for statement in sql_path.read_text().split(";")]
    for statement in statements:
        if statement:
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS snapshots")
    op.execute("DROP TABLE IF EXISTS review_flags")
    op.execute("DROP TABLE IF EXISTS meeting_occurrences")
    op.execute("DROP TABLE IF EXISTS canonical_meetings")
    op.execute("DROP TABLE IF EXISTS raw_meetings")
    op.execute("DROP TABLE IF EXISTS import_runs")
    op.execute("DROP TABLE IF EXISTS sources")

