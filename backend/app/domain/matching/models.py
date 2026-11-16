"""Inputs and outputs of the matching engine.

These models are the reconciliation contract. They are not database rows and
they are not HTTP schemas.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.decimals import StrictDecimal, format_decimal


class DocumentType(StrEnum):
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_NOTE = "delivery_note"
    INVOICE = "invoice"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class FindingCode(StrEnum):
    LINE_RECONCILED = "LINE_RECONCILED"
    ORDERED_NOT_DELIVERED = "ORDERED_NOT_DELIVERED"
    DELIVERED_NOT_ORDERED = "DELIVERED_NOT_ORDERED"
    INVOICED_WITHOUT_DELIVERY = "INVOICED_WITHOUT_DELIVERY"
    DELIVERED_NOT_INVOICED = "DELIVERED_NOT_INVOICED"
    INVOICED_NOT_ORDERED = "INVOICED_NOT_ORDERED"
    ORDERED_NOT_INVOICED = "ORDERED_NOT_INVOICED"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    INCONSISTENT_UNIT_PRICE = "INCONSISTENT_UNIT_PRICE"
    MISSING_UNIT_PRICE = "MISSING_UNIT_PRICE"
    UNCERTAIN_PRODUCT_MAPPING = "UNCERTAIN_PRODUCT_MAPPING"
    MISSING_PURCHASE_ORDER = "MISSING_PURCHASE_ORDER"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    REFERENCE_MISMATCH = "REFERENCE_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    MISSING_CURRENCY = "MISSING_CURRENCY"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    NO_LINES = "NO_LINES"


class ReconciliationInputError(ValueError):
    """The records cannot be reconciled because they violate the input contract."""


class MatchConfig(BaseModel):
    """Absolute tolerances. The demonstration default is exact equality."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity_tolerance: StrictDecimal = Decimal("0")
    price_tolerance: StrictDecimal = Decimal("0")

    @model_validator(mode="after")
    def tolerances_are_not_negative(self) -> "MatchConfig":
        if self.quantity_tolerance < 0 or self.price_tolerance < 0:
            raise ValueError("Tolerances must be zero or positive.")
        return self


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: DocumentType
    document_number: str
    purchase_order_number: str | None = None
    currency: str | None = None


class SourceLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: DocumentType
    document_number: str
    line_number: int
    product_code: str | None
    description: str
    quantity: StrictDecimal
    unit: str
    unit_price: StrictDecimal | None = None
    currency: str | None = None


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: DocumentType
    document_number: str
    line_number: int | None = None


class ReconciliationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: list[SourceDocument] = Field(default_factory=list)
    lines: list[SourceLine] = Field(default_factory=list)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: FindingCode
    status: MatchStatus
    product_code: str | None = None
    message: str
    unit: str | None = None
    currency: str | None = None
    ordered_quantity: StrictDecimal | None = None
    delivered_quantity: StrictDecimal | None = None
    invoiced_quantity: StrictDecimal | None = None
    quantity_difference: StrictDecimal | None = None
    purchase_order_unit_price: StrictDecimal | None = None
    invoice_unit_price: StrictDecimal | None = None
    price_difference: StrictDecimal | None = None
    source_references: list[SourceReference] = Field(default_factory=list)


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: MatchStatus
    findings: list[Finding]

    def finding_codes(self) -> list[FindingCode]:
        return [finding.code for finding in self.findings]


def canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format_decimal(value)
