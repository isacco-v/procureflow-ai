"""HTTP contracts for uploaded documents and explicit acceptance."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.decimals import ApiDecimal
from app.domain.matching.models import DocumentType, MatchStatus


class TextBlockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    bbox: list[float]


class DocumentPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    blocks: list[TextBlockResponse]


class SourceSnippetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    page_number: int
    snippet: str


class ExtractedLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int | None
    product_code: str | None
    description: str | None
    quantity: str | None
    unit: str | None
    unit_price: str | None
    line_total: str | None


class ExtractedDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType | None
    document_number: str | None
    supplier_name: str | None
    supplier_code: str | None
    purchase_order_number: str | None
    document_date: str | None
    currency: str | None
    lines: list[ExtractedLineResponse]
    net_amount: str | None
    tax_rate_percent: str | None
    tax_amount: str | None
    amount_due: str | None
    uncertainties: list[str]
    source_references: list[SourceSnippetResponse]


class ValidationWarningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["blocking", "advisory"]
    message: str
    field: str | None = None


class ExtractionValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "blocked"]
    blocking: bool
    warnings: list[ValidationWarningResponse]
    normalized: dict[str, object] | None
    computed: dict[str, object]


class UploadSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    original_filename: str
    byte_size: int
    sha256: str
    page_count: int | None
    status: Literal["needs_review", "accepted", "failed"]
    stages: list[str]
    error_code: str | None
    error_detail: str | None
    image_only: bool
    text_extractable: bool
    ocr_applied: Literal[False]
    ocr_implemented: Literal[False] = False
    content_source: Literal["page_text"] = "page_text"
    extractor: Literal["mock", "openai"] | None
    mocked: bool | None
    model_name: str | None
    reasoning_kind: Literal["deterministic_test_double", "language_model"] | None
    document_type: DocumentType | None
    document_number: str | None
    accepted_case_id: UUID | None
    duplicate: bool
    created_at: datetime


class UploadDetailResponse(UploadSummaryResponse):
    media_type: str
    char_count: int
    pdf_metadata: dict[str, str]
    pages: list[DocumentPageResponse]
    extraction: ExtractedDocumentResponse | None
    validation: ExtractionValidationResponse | None
    prompt_injection_flags: list[str]
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: ApiDecimal | None


class UploadListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[UploadSummaryResponse]


class AcceptDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    case_id: UUID
    case_reference: str
    procurement_document_id: UUID
    origin: Literal["upload"] = "upload"
    synthetic: Literal[False] = False
    replayed: bool
    reconciliation_id: UUID | None
    reconciliation_status: MatchStatus | None
    reconciliation_error: str | None = Field(default=None)
