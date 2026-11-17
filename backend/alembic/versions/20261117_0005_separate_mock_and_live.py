"""Keep mock and live investigations and extractions on separate rows.

Revision ID: 20261117_0005
Revises: 20261117_0004
Create Date: 2026-11-17

Existing rows stay in place. A mock investigation is no longer the only row
allowed for a reconciliation run, and a mock extraction is no longer the only
extraction allowed for an uploaded file. Acceptance still points at the
extraction that was written into the procurement tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_0005"
down_revision: str | Sequence[str] | None = "20261117_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uploaded_documents",
        sa.Column("accepted_extraction_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "document_extractions",
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_extractions",
        sa.Column("error_detail", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE uploaded_documents AS upload
        SET accepted_extraction_id = extraction.id
        FROM document_extractions AS extraction
        WHERE extraction.uploaded_document_id = upload.id
          AND upload.status = 'accepted'
          AND extraction.error_code IS NULL
        """
    )
    op.create_foreign_key(
        "fk_uploaded_documents_accepted_extraction_id",
        "uploaded_documents",
        "document_extractions",
        ["accepted_extraction_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "document_extractions_uploaded_document_id_key",
        "document_extractions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_document_extractions_upload_provider",
        "document_extractions",
        ["uploaded_document_id", "provider"],
    )
    op.drop_constraint(
        "uq_investigations_reconciliation_run_id",
        "investigations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_investigations_run_ai_mode",
        "investigations",
        ["reconciliation_run_id", "ai_mode"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_investigations_run_ai_mode", "investigations", type_="unique")
    op.create_unique_constraint(
        "uq_investigations_reconciliation_run_id",
        "investigations",
        ["reconciliation_run_id"],
    )
    op.drop_constraint(
        "uq_document_extractions_upload_provider",
        "document_extractions",
        type_="unique",
    )
    op.create_unique_constraint(
        "document_extractions_uploaded_document_id_key",
        "document_extractions",
        ["uploaded_document_id"],
    )
    op.drop_constraint(
        "fk_uploaded_documents_accepted_extraction_id",
        "uploaded_documents",
        type_="foreignkey",
    )
    op.drop_column("document_extractions", "error_detail")
    op.drop_column("document_extractions", "error_code")
    op.drop_column("uploaded_documents", "accepted_extraction_id")
