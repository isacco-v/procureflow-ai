"""Uploaded PDFs, parsed pages, and staged extractions.

An upload is not a procurement record. Acceptance copies a validated extraction
into the commercial tables and keeps the upload id on that source document.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.procurement import utcnow

_COST = Numeric(18, 6)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    original_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stages: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    text_extractable: Mapped[bool] = mapped_column(nullable=False)
    image_only: Mapped[bool] = mapped_column(nullable=False)
    ocr_applied: Mapped[bool] = mapped_column(nullable=False, default=False)
    char_count: Mapped[int] = mapped_column(nullable=False)
    pdf_metadata: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    accepted_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("procurement_cases.id"),
        nullable=True,
    )
    accepted_extraction_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "document_extractions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_uploaded_documents_accepted_extraction_id",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="upload",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
    )
    extractions: Mapped[list[DocumentExtraction]] = relationship(
        back_populates="upload",
        cascade="all, delete-orphan",
        order_by="DocumentExtraction.created_at",
        foreign_keys="DocumentExtraction.uploaded_document_id",
    )

    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_uploaded_documents_byte_size"),
        CheckConstraint("char_count >= 0", name="ck_uploaded_documents_char_count"),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_uploaded_documents_page_count",
        ),
        CheckConstraint(
            "status IN ('needs_review', 'accepted', 'failed')",
            name="ck_uploaded_documents_status",
        ),
        CheckConstraint("ocr_applied = false", name="ck_uploaded_documents_ocr_applied"),
        CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="ck_uploaded_documents_sha256"),
        Index("ix_uploaded_documents_status", "status"),
        Index("ix_uploaded_documents_accepted_case_id", "accepted_case_id"),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    uploaded_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    blocks: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

    upload: Mapped[UploadedDocument] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint(
            "uploaded_document_id",
            "page_number",
            name="uq_document_pages_upload_page",
        ),
        CheckConstraint("page_number > 0", name="ck_document_pages_page_number"),
        Index("ix_document_pages_uploaded_document_id", "uploaded_document_id"),
    )


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    uploaded_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    mocked: Mapped[bool] = mapped_column(nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    prompt_injection_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(_COST, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    upload: Mapped[UploadedDocument] = relationship(
        back_populates="extractions",
        foreign_keys="DocumentExtraction.uploaded_document_id",
    )
    validation: Mapped[ExtractionValidation | None] = relationship(
        back_populates="extraction",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "uploaded_document_id",
            "provider",
            name="uq_document_extractions_upload_provider",
        ),
        CheckConstraint(
            "provider IN ('mock', 'openai')",
            name="ck_document_extractions_provider",
        ),
        CheckConstraint(
            "reasoning_kind IN ('deterministic_test_double', 'language_model')",
            name="ck_document_extractions_reasoning_kind",
        ),
        CheckConstraint("input_tokens >= 0", name="ck_document_extractions_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_document_extractions_output_tokens"),
        CheckConstraint(
            "estimated_cost_usd >= 0",
            name="ck_document_extractions_estimated_cost",
        ),
        CheckConstraint(
            "(provider = 'mock' AND mocked = true "
            "AND reasoning_kind = 'deterministic_test_double') "
            "OR (provider = 'openai' AND mocked = false "
            "AND reasoning_kind = 'language_model')",
            name="ck_document_extractions_mock_consistency",
        ),
    )


class ExtractionValidation(Base):
    __tablename__ = "extraction_validations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    blocking: Mapped[bool] = mapped_column(nullable=False)
    warnings: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    normalized: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    computed: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    extraction: Mapped[DocumentExtraction] = relationship(back_populates="validation")

    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'blocked')",
            name="ck_extraction_validations_status",
        ),
        CheckConstraint(
            "(status = 'blocked' AND blocking = true) OR (status = 'ready' AND blocking = false)",
            name="ck_extraction_validations_blocking",
        ),
    )
