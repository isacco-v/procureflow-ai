"""SQLAlchemy models for procurement cases and reconciliation results."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from app.domain.matching.models import DocumentType, FindingCode, MatchStatus

_QUANTITY = Numeric(18, 4)
_MONEY = Numeric(18, 4)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _status_check(column: str, name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{status.value}'" for status in MatchStatus)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def _code_check(name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{code.value}'" for code in FindingCode)
    return CheckConstraint(f"code IN ({allowed})", name=name)


def _document_type_check(name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{item.value}'" for item in DocumentType)
    return CheckConstraint(f"document_type IN ({allowed})", name=name)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    synthetic: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    cases: Mapped[list[ProcurementCase]] = relationship(back_populates="supplier")


class ProcurementCase(Base):
    __tablename__ = "procurement_cases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    synthetic: Mapped[bool] = mapped_column(nullable=False)
    origin: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="synthetic_seed",
        server_default="synthetic_seed",
    )
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    supplier: Mapped[Supplier] = relationship(back_populates="cases")
    documents: Mapped[list[ProcurementDocument]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )
    purchase_order: Mapped[PurchaseOrder | None] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        uselist=False,
    )
    delivery_notes: Mapped[list[DeliveryNote]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )
    reconciliation_runs: Mapped[list[ReconciliationRun]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "origin IN ('synthetic_seed', 'upload')",
            name="ck_procurement_cases_origin",
        ),
        Index("ix_procurement_cases_supplier_id", "supplier_id"),
    )


class ProcurementDocument(Base):
    __tablename__ = "procurement_documents"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_number: Mapped[str] = mapped_column(String(64), nullable=False)
    synthetic: Mapped[bool] = mapped_column(nullable=False)
    origin: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="synthetic_seed",
        server_default="synthetic_seed",
    )
    upload_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("uploaded_documents.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    case: Mapped[ProcurementCase] = relationship(back_populates="documents")

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "document_type",
            "document_number",
            name="uq_procurement_documents_case_type_number",
        ),
        _document_type_check("ck_procurement_documents_type"),
        CheckConstraint(
            "origin IN ('synthetic_seed', 'upload')",
            name="ck_procurement_documents_origin",
        ),
        Index("ix_procurement_documents_case_id", "case_id"),
        Index("ix_procurement_documents_upload_id", "upload_id"),
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
        unique=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)

    case: Mapped[ProcurementCase] = relationship(back_populates="purchase_order")
    source_document: Mapped[ProcurementDocument] = relationship()
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_number",
    )

    __table_args__ = (
        UniqueConstraint("supplier_id", "number", name="uq_purchase_orders_supplier_number"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_purchase_orders_currency"),
        Index("ix_purchase_orders_supplier_id", "supplier_id"),
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    purchase_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    source_document: Mapped[ProcurementDocument] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id",
            "line_number",
            name="uq_purchase_order_lines_order_line",
        ),
        CheckConstraint("line_number > 0", name="ck_purchase_order_lines_line_number"),
        CheckConstraint("quantity > 0", name="ck_purchase_order_lines_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_purchase_order_lines_unit_price"),
        CheckConstraint(
            "char_length(btrim(description)) > 0",
            name="ck_purchase_order_lines_description",
        ),
        CheckConstraint("char_length(btrim(unit)) > 0", name="ck_purchase_order_lines_unit"),
        CheckConstraint(
            "product_code IS NULL OR char_length(btrim(product_code)) > 0",
            name="ck_purchase_order_lines_product_code",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_purchase_order_lines_currency"),
        Index("ix_purchase_order_lines_purchase_order_id", "purchase_order_id"),
        Index("ix_purchase_order_lines_source_document_id", "source_document_id"),
    )


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
        unique=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_order_number: Mapped[str | None] = mapped_column(String(64))
    delivered_on: Mapped[date] = mapped_column(Date, nullable=False)

    case: Mapped[ProcurementCase] = relationship(back_populates="delivery_notes")
    source_document: Mapped[ProcurementDocument] = relationship()
    lines: Mapped[list[DeliveryNoteLine]] = relationship(
        back_populates="delivery_note",
        cascade="all, delete-orphan",
        order_by="DeliveryNoteLine.line_number",
    )

    __table_args__ = (
        UniqueConstraint("supplier_id", "number", name="uq_delivery_notes_supplier_number"),
        Index("ix_delivery_notes_case_id", "case_id"),
    )


class DeliveryNoteLine(Base):
    __tablename__ = "delivery_note_lines"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    delivery_note_id: Mapped[UUID] = mapped_column(
        ForeignKey("delivery_notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    delivery_note: Mapped[DeliveryNote] = relationship(back_populates="lines")
    source_document: Mapped[ProcurementDocument] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "delivery_note_id",
            "line_number",
            name="uq_delivery_note_lines_note_line",
        ),
        CheckConstraint("line_number > 0", name="ck_delivery_note_lines_line_number"),
        CheckConstraint("quantity > 0", name="ck_delivery_note_lines_quantity"),
        CheckConstraint(
            "char_length(btrim(description)) > 0",
            name="ck_delivery_note_lines_description",
        ),
        CheckConstraint("char_length(btrim(unit)) > 0", name="ck_delivery_note_lines_unit"),
        CheckConstraint(
            "product_code IS NULL OR char_length(btrim(product_code)) > 0",
            name="ck_delivery_note_lines_product_code",
        ),
        Index("ix_delivery_note_lines_delivery_note_id", "delivery_note_id"),
        Index("ix_delivery_note_lines_source_document_id", "source_document_id"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
        unique=True,
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_order_number: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)

    case: Mapped[ProcurementCase] = relationship(back_populates="invoices")
    source_document: Mapped[ProcurementDocument] = relationship()
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLine.line_number",
    )

    __table_args__ = (
        UniqueConstraint("supplier_id", "number", name="uq_invoices_supplier_number"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_invoices_currency"),
        Index("ix_invoices_case_id", "case_id"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_documents.id"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    source_document: Mapped[ProcurementDocument] = relationship()

    __table_args__ = (
        UniqueConstraint("invoice_id", "line_number", name="uq_invoice_lines_invoice_line"),
        CheckConstraint("line_number > 0", name="ck_invoice_lines_line_number"),
        CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price"),
        CheckConstraint(
            "char_length(btrim(description)) > 0",
            name="ck_invoice_lines_description",
        ),
        CheckConstraint("char_length(btrim(unit)) > 0", name="ck_invoice_lines_unit"),
        CheckConstraint(
            "product_code IS NULL OR char_length(btrim(product_code)) > 0",
            name="ck_invoice_lines_product_code",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_invoice_lines_currency"),
        Index("ix_invoice_lines_invoice_id", "invoice_id"),
        Index("ix_invoice_lines_source_document_id", "source_document_id"),
    )


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("procurement_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    case: Mapped[ProcurementCase] = relationship(back_populates="reconciliation_runs")
    findings: Mapped[list[ReconciliationFinding]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ReconciliationFinding.ordinal",
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "input_fingerprint",
            name="uq_reconciliation_runs_case_fingerprint",
        ),
        _status_check("status", "ck_reconciliation_runs_status"),
        Index("ix_reconciliation_runs_case_id", "case_id"),
    )


class ReconciliationFinding(Base):
    __tablename__ = "reconciliation_findings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str | None] = mapped_column(String(3))
    ordered_quantity: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    delivered_quantity: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    invoiced_quantity: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    quantity_difference: Mapped[Decimal | None] = mapped_column(_QUANTITY)
    purchase_order_unit_price: Mapped[Decimal | None] = mapped_column(_MONEY)
    invoice_unit_price: Mapped[Decimal | None] = mapped_column(_MONEY)
    price_difference: Mapped[Decimal | None] = mapped_column(_MONEY)
    source_references: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

    run: Mapped[ReconciliationRun] = relationship(back_populates="findings")

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_reconciliation_findings_run_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_reconciliation_findings_ordinal"),
        _code_check("ck_reconciliation_findings_code"),
        _status_check("status", "ck_reconciliation_findings_status"),
        Index("ix_reconciliation_findings_run_id", "run_id"),
    )
