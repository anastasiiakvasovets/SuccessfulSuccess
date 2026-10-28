"""a meeting's agenda, and the AI suggestion it started from (Lab 6)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # What the user saved: {"items": [...], "action_items": [...]}.
    op.add_column("meetings", sa.Column("agenda", JSONB(), nullable=True))
    # What the parser suggested before the user corrected it, and which model
    # and prompt produced it. The difference is the parser's quality signal.
    op.add_column("meetings", sa.Column("ai_suggestion", JSONB(), nullable=True))
    op.add_column("meetings", sa.Column("ai_model", sa.String(100), nullable=True))
    op.add_column("meetings", sa.Column("ai_prompt_version", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "ai_prompt_version")
    op.drop_column("meetings", "ai_model")
    op.drop_column("meetings", "ai_suggestion")
    op.drop_column("meetings", "agenda")
