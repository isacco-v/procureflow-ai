"""Typed records shared by parsing, extraction, and validation.

These are not database rows and they are not HTTP schemas. Money stays in
decimal strings until the validation step parses it with ``Decimal``.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.matching.models import DocumentType


class SourceSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=80)
    page_number: int = Field(ge=1)
    snippet: str = Field(min_length=1, max_length=240)


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int | None = None
    product_code: str | None = None
    description: str | None = None
    quantity: str | None = None
    unit: str | None = None
    unit_price: str | None = None
    line_total: str | None = None


class ExtractedDocument(BaseModel):
    """Fields read from page text. Missing values stay null."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType | None = None
    document_number: str | None = None
    supplier_name: str | None = None
    supplier_code: str | None = None
    purchase_order_number: str | None = None
    document_date: str | None = None
    currency: str | None = None
    lines: list[ExtractedLine] = Field(default_factory=list)
    net_amount: str | None = None
    tax_rate_percent: str | None = None
    tax_amount: str | None = None
    amount_due: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    source_references: list[SourceSnippet] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    text: str
    blocks: tuple[TextBlock, ...]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Text PyMuPDF could read. Metadata is recorded and is not an identifier."""

    page_count: int
    pages: tuple[ParsedPage, ...]
    metadata: dict[str, str]
    image_only: bool
    text_extractable: bool
    char_count: int


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    document: ExtractedDocument
    provider: Literal["mock", "openai"]
    mocked: bool
    model_name: str
    reasoning_kind: Literal["deterministic_test_double", "language_model"]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    prompt_injection_flags: list[str] = field(default_factory=list)


class ValidationWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["blocking", "advisory"]
    message: str
    field: str | None = None


class NormalizedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int
    product_code: str | None
    description: str
    quantity: str
    unit: str
    unit_price: str | None
    line_total: str | None


class NormalizedDocument(BaseModel):
    """Candidate commercial record. It is not authoritative until a person accepts it."""

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    document_number: str
    supplier_name: str
    supplier_code: str
    purchase_order_number: str | None
    document_date: str
    currency: str | None
    lines: list[NormalizedLine]
    net_amount: str | None
    tax_rate_percent: str | None
    tax_amount: str | None
    amount_due: str | None
    unresolved_product_lines: list[int]


class ComputedAmounts(BaseModel):
    """Decimal arithmetic performed by application code, not by a model."""

    model_config = ConfigDict(extra="forbid")

    line_totals: list[str | None]
    net_amount: str | None
    tax_amount: str | None
    amount_due: str | None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "blocked"]
    blocking: bool
    warnings: list[ValidationWarning]
    normalized: NormalizedDocument | None
    computed: ComputedAmounts
