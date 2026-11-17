"""Store investigation attempts without rewriting earlier results.

Revision ID: 20261117_0006
Revises: 20261117_0005
Create Date: 2026-11-17

Existing investigation rows stay in place. Their status, summary, action, and
events are not updated. A new nullable evidence flag and empty text lists are
added so a later attempt can be stored beside the original row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_0006"
down_revision: str | Sequence[str] | None = "20261117_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY_LIST = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "investigations",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column("evidence_validated", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "observed_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_EMPTY_LIST,
        ),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "possible_explanations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_EMPTY_LIST,
        ),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "missing_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_EMPTY_LIST,
        ),
    )
    op.add_column(
        "investigations",
        sa.Column(
            "next_actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=_EMPTY_LIST,
        ),
    )
    op.alter_column("investigations", "attempt", server_default=None)
    op.alter_column("investigations", "observed_facts", server_default=None)
    op.alter_column("investigations", "possible_explanations", server_default=None)
    op.alter_column("investigations", "missing_evidence", server_default=None)
    op.alter_column("investigations", "next_actions", server_default=None)
    op.create_check_constraint(
        "ck_investigations_attempt",
        "investigations",
        "attempt >= 1",
    )
    op.drop_constraint("uq_investigations_run_ai_mode", "investigations", type_="unique")
    op.create_unique_constraint(
        "uq_investigations_run_mode_attempt",
        "investigations",
        ["reconciliation_run_id", "ai_mode", "attempt"],
    )
    op.create_unique_constraint(
        "uq_investigations_run_mode_idempotency",
        "investigations",
        ["reconciliation_run_id", "ai_mode", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_investigations_run_mode_idempotency",
        "investigations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_investigations_run_mode_attempt",
        "investigations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_investigations_run_ai_mode",
        "investigations",
        ["reconciliation_run_id", "ai_mode"],
    )
    op.drop_constraint("ck_investigations_attempt", "investigations", type_="check")
    op.drop_column("investigations", "next_actions")
    op.drop_column("investigations", "missing_evidence")
    op.drop_column("investigations", "possible_explanations")
    op.drop_column("investigations", "observed_facts")
    op.drop_column("investigations", "evidence_validated")
    op.drop_column("investigations", "idempotency_key")
    op.drop_column("investigations", "attempt")
