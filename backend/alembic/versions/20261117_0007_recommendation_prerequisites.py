"""Store structured recommendation prerequisites beside earlier attempts.

Revision ID: 20261117_0007
Revises: 20261117_0006
Create Date: 2026-11-17

Existing investigation rows stay in place. Their status, summary, action, and
events are not updated. The new list is empty for those rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_0007"
down_revision: str | Sequence[str] | None = "20261117_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column(
            "prerequisites",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_EMPTY_LIST,
        ),
    )
    op.alter_column("investigations", "prerequisites", server_default=None)


def downgrade() -> None:
    op.drop_column("investigations", "prerequisites")
