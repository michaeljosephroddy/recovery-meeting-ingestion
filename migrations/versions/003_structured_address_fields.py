"""Add structured address fields to canonical meetings.

Revision ID: 003_structured_address_fields
Revises: 002_missing_run_count
Create Date: 2026-05-26
"""

from alembic import op

revision = "003_structured_address_fields"
down_revision = "002_missing_run_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE canonical_meetings ADD COLUMN IF NOT EXISTS region_code TEXT")
    op.execute("ALTER TABLE canonical_meetings ADD COLUMN IF NOT EXISTS country_code TEXT")
    op.execute("ALTER TABLE canonical_meetings ADD COLUMN IF NOT EXISTS raw_location_text TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE canonical_meetings DROP COLUMN IF EXISTS raw_location_text")
    op.execute("ALTER TABLE canonical_meetings DROP COLUMN IF EXISTS country_code")
    op.execute("ALTER TABLE canonical_meetings DROP COLUMN IF EXISTS region_code")
