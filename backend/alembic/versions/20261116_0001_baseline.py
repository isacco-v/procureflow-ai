"""Baseline revision.

Domain tables are intentionally absent. They arrive with the first functional
slice, after the reconciliation contract is defined and tested.

Revision ID: 20261116_0001
Revises:
Create Date: 2026-11-16
"""

from collections.abc import Sequence

revision: str = "20261116_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
