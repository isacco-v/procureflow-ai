"""HTTP contracts for procurement cases and reconciliation runs."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.decimals import ApiDecimal
from app.domain.matching.models import DocumentType, FindingCode, MatchStatus


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str


class SupplierResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    synthetic: bool


class DocumentLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int
    product_code: str | None
    description: str
    quantity: ApiDecimal
    unit: str
    unit_price: ApiDecimal | None = None
    currency: str | None = None
    source_document_id: UUID


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    number: str
    currency: str
    issued_on: date
    source_document_id: UUID
    lines: list[DocumentLineResponse]


class DeliveryNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    number: str
    purchase_order_number: str | None
    delivered_on: date
    source_document_id: UUID
    lines: list[DocumentLineResponse]


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    number: str
    purchase_order_number: str | None
    currency: str
    issued_on: date
    source_document_id: UUID
    lines: list[DocumentLineResponse]


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    document_type: DocumentType
    document_number: str
    synthetic: bool


class CaseSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    reference: str
    title: str
    summary: str
    synthetic: bool
    supplier: SupplierResponse
    latest_reconciliation_id: UUID | None
    latest_reconciliation_status: MatchStatus | None


class CaseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[CaseSummaryResponse]


class CaseDetailResponse(CaseSummaryResponse):
    documents: list[SourceDocumentResponse]
    purchase_order: PurchaseOrderResponse | None
    delivery_notes: list[DeliveryNoteResponse]
    invoices: list[InvoiceResponse]


class SourceReferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    document_number: str
    line_number: int | None = None
    document_id: UUID | None = None


class FindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: FindingCode
    status: MatchStatus
    product_code: str | None
    message: str
    unit: str | None
    currency: str | None
    ordered_quantity: ApiDecimal | None
    delivered_quantity: ApiDecimal | None
    invoiced_quantity: ApiDecimal | None
    quantity_difference: ApiDecimal | None
    purchase_order_unit_price: ApiDecimal | None
    invoice_unit_price: ApiDecimal | None
    price_difference: ApiDecimal | None
    source_references: list[SourceReferenceResponse]


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    case_id: UUID
    status: MatchStatus
    engine_version: str
    input_fingerprint: str
    created_at: datetime
    replayed: bool
    findings: list[FindingResponse]


class SeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthetic: Literal[True] = True
    cases_created: list[str] = Field(default_factory=list)
    cases_existing: list[str] = Field(default_factory=list)
