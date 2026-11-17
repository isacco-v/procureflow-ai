"""Document intake tables and provenance columns on procurement records.

Revision ID: 20261117_0004
Revises: 20261117_0003
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_0004"
down_revision: str | Sequence[str] | None = "20261117_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploaded_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=200), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("text_extractable", sa.Boolean(), nullable=False),
        sa.Column("image_only", sa.Boolean(), nullable=False),
        sa.Column("ocr_applied", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("pdf_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_case_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size > 0", name="ck_uploaded_documents_byte_size"),
        sa.CheckConstraint("char_count >= 0", name="ck_uploaded_documents_char_count"),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_uploaded_documents_page_count",
        ),
        sa.CheckConstraint(
            "status IN ('needs_review', 'accepted', 'failed')",
            name="ck_uploaded_documents_status",
        ),
        sa.CheckConstraint("ocr_applied = false", name="ck_uploaded_documents_ocr_applied"),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_uploaded_documents_sha256"),
        sa.ForeignKeyConstraint(
            ["accepted_case_id"],
            ["procurement_cases.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_uploaded_documents_status", "uploaded_documents", ["status"], unique=False)
    op.create_index(
        "ix_uploaded_documents_accepted_case_id",
        "uploaded_documents",
        ["accepted_case_id"],
        unique=False,
    )
    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("page_number > 0", name="ck_document_pages_page_number"),
        sa.ForeignKeyConstraint(
            ["uploaded_document_id"],
            ["uploaded_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "uploaded_document_id",
            "page_number",
            name="uq_document_pages_upload_page",
        ),
    )
    op.create_index(
        "ix_document_pages_uploaded_document_id",
        "document_pages",
        ["uploaded_document_id"],
        unique=False,
    )
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_document_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("mocked", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("reasoning_kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "prompt_injection_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('mock', 'openai')",
            name="ck_document_extractions_provider",
        ),
        sa.CheckConstraint(
            "reasoning_kind IN ('deterministic_test_double', 'language_model')",
            name="ck_document_extractions_reasoning_kind",
        ),
        sa.CheckConstraint("input_tokens >= 0", name="ck_document_extractions_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_document_extractions_output_tokens"),
        sa.CheckConstraint(
            "estimated_cost_usd >= 0",
            name="ck_document_extractions_estimated_cost",
        ),
        sa.CheckConstraint(
            "(provider = 'mock' AND mocked = true "
            "AND reasoning_kind = 'deterministic_test_double') "
            "OR (provider = 'openai' AND mocked = false "
            "AND reasoning_kind = 'language_model')",
            name="ck_document_extractions_mock_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_document_id"],
            ["uploaded_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uploaded_document_id"),
    )
    op.create_table(
        "extraction_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "status IN ('ready', 'blocked')",
            name="ck_extraction_validations_status",
        ),
        sa.CheckConstraint(
            "(status = 'blocked' AND blocking = true) OR (status = 'ready' AND blocking = false)",
            name="ck_extraction_validations_blocking",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["document_extractions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_id"),
    )
    op.add_column(
        "procurement_cases",
        sa.Column(
            "origin",
            sa.String(length=32),
            server_default="synthetic_seed",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_procurement_cases_origin",
        "procurement_cases",
        "origin IN ('synthetic_seed', 'upload')",
    )
    op.add_column(
        "procurement_documents",
        sa.Column(
            "origin",
            sa.String(length=32),
            server_default="synthetic_seed",
            nullable=False,
        ),
    )
    op.add_column(
        "procurement_documents",
        sa.Column("upload_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_procurement_documents_upload_id",
        "procurement_documents",
        "uploaded_documents",
        ["upload_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_procurement_documents_origin",
        "procurement_documents",
        "origin IN ('synthetic_seed', 'upload')",
    )
    op.create_index(
        "ix_procurement_documents_upload_id",
        "procurement_documents",
        ["upload_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_procurement_documents_upload_id", table_name="procurement_documents")
    op.drop_constraint("ck_procurement_documents_origin", "procurement_documents", type_="check")
    op.drop_constraint(
        "fk_procurement_documents_upload_id", "procurement_documents", type_="foreignkey"
    )
    op.drop_column("procurement_documents", "upload_id")
    op.drop_column("procurement_documents", "origin")
    op.drop_constraint("ck_procurement_cases_origin", "procurement_cases", type_="check")
    op.drop_column("procurement_cases", "origin")
    op.drop_table("extraction_validations")
    op.drop_table("document_extractions")
    op.drop_index("ix_document_pages_uploaded_document_id", table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index("ix_uploaded_documents_accepted_case_id", table_name="uploaded_documents")
    op.drop_index("ix_uploaded_documents_status", table_name="uploaded_documents")
    op.drop_table("uploaded_documents")
