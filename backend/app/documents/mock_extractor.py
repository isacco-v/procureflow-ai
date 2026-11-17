"""Deterministic extractor for labeled synthetic page text.

This is a test double. It reads labels from the page text produced by the
parser. It does not receive a file name, a content hash, or a fixture id, and
it does not call a language model. Missing and contradictory labels stay empty.
"""

import re
from decimal import Decimal

from app.documents.injection import find_prompt_injection
from app.documents.models import (
    ExtractedDocument,
    ExtractedLine,
    ExtractionOutcome,
    ParsedDocument,
    SourceSnippet,
)
from app.domain.matching.models import DocumentType

_NOT_STATED = "NOT STATED"
_HEADINGS: dict[str, DocumentType] = {
    "WORKS ORDER": DocumentType.PURCHASE_ORDER,
    "GOODS RECEIVED NOTE": DocumentType.DELIVERY_NOTE,
    "DELIVERY TICKET": DocumentType.DELIVERY_NOTE,
    "SUPPLIER TAX INVOICE": DocumentType.INVOICE,
}
_DOCUMENT_LABELS: dict[str, str] = {
    "supplier name": "supplier_name",
    "received from": "supplier_name",
    "haulier": "supplier_name",
    "supplier account": "supplier_code",
    "account code": "supplier_code",
    "customer account": "supplier_code",
    "works order number": "document_number",
    "goods received number": "document_number",
    "ticket": "document_number",
    "invoice number": "document_number",
    "order date": "document_date",
    "date received": "document_date",
    "dispatch date": "document_date",
    "invoice date": "document_date",
    "currency code": "currency",
    "site reference": "purchase_order_number",
    "order number": "purchase_order_number",
    "customer purchase order": "purchase_order_number",
    "customer order": "purchase_order_number",
    "net amount": "net_amount",
    "tax": "tax_amount",
    "vat rate percent": "tax_rate_percent",
    "vat amount": "tax_amount",
    "amount due": "amount_due",
}
_LINE_LABELS: dict[str, str] = {
    "product code": "product_code",
    "description": "description",
    "quantity": "quantity",
    "quantity received": "quantity",
    "unit of measure": "unit",
    "unit price": "unit_price",
    "line amount": "line_total",
}
_LABEL_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ]*?):\s*(?P<value>.+)$")
_LINE_HEADING = re.compile(r"^Line\s+(?P<number>\d+)$")
_ITEM_LINE = re.compile(
    r"^Item\s+(?P<number>\d+):\s*code=(?P<code>[^;]+);\s*material=(?P<material>[^;]+);\s*"
    r"quantity=(?P<quantity>[^;]+);\s*unit=(?P<unit>.+)$"
)
_PAGE_FOOTER = re.compile(r"^Page\s+\d+\s+of\s+\d+$")
_SNIPPET_LIMIT = 240


class _Slot:
    def __init__(self) -> None:
        self.value: str | None = None
        self.seen = False
        self.conflict = False


class MockDocumentExtractor:
    """Scripted reader for the synthetic layouts. Explicitly not document understanding."""

    name = "mock"
    model_name = "mock-document-extractor"
    mocked = True
    reasoning_kind = "deterministic_test_double"

    def extract(self, parsed: ParsedDocument) -> ExtractionOutcome:
        page_text = "\n".join(page.text for page in parsed.pages)
        flags = find_prompt_injection(page_text)
        document = _read_pages(parsed)
        if flags:
            document.uncertainties.append(
                "The page text contains instruction-like phrases. They were ignored."
            )
        return ExtractionOutcome(
            document=document,
            provider="mock",
            mocked=True,
            model_name=self.model_name,
            reasoning_kind="deterministic_test_double",
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=Decimal("0"),
            prompt_injection_flags=flags,
        )


def _read_pages(parsed: ParsedDocument) -> ExtractedDocument:
    rows: list[tuple[int, str]] = []
    for page in parsed.pages:
        for raw in page.text.splitlines():
            text = raw.strip()
            if text and not _PAGE_FOOTER.match(text):
                rows.append((page.page_number, text))

    document_type, type_conflicts = _document_type(rows)
    slots: dict[str, _Slot] = {}
    references: list[SourceSnippet] = []
    uncertainties: list[str] = []
    lines: dict[int, dict[str, _Slot]] = {}
    current: int | None = None

    if type_conflicts:
        document_type = None
        uncertainties.append("document_type is contradictory and was left empty")
    elif document_type is None:
        uncertainties.append("document_type was not found in the page text")

    for page_number, text in rows:
        item = _ITEM_LINE.match(text)
        if item is not None:
            current = int(item.group("number"))
            bucket = lines.setdefault(current, {})
            _put(
                bucket,
                "product_code",
                item.group("code"),
                page_number,
                text,
                references,
                uncertainties,
            )
            _put(
                bucket,
                "description",
                item.group("material"),
                page_number,
                text,
                references,
                uncertainties,
            )
            _put(
                bucket,
                "quantity",
                item.group("quantity"),
                page_number,
                text,
                references,
                uncertainties,
            )
            _put(bucket, "unit", item.group("unit"), page_number, text, references, uncertainties)
            continue
        heading = _LINE_HEADING.match(text)
        if heading is not None:
            current = int(heading.group("number"))
            lines.setdefault(current, {})
            continue
        label_match = _LABEL_LINE.match(text)
        if label_match is None:
            continue
        label = " ".join(label_match.group("label").lower().split())
        value = label_match.group("value").strip()
        if label in _LINE_LABELS:
            if current is None:
                uncertainties.append(f"{_LINE_LABELS[label]} appeared outside a line")
                continue
            bucket = lines.setdefault(current, {})
            _put(bucket, _LINE_LABELS[label], value, page_number, text, references, uncertainties)
            continue
        if label in _DOCUMENT_LABELS:
            current = None
            _put(
                slots,
                _DOCUMENT_LABELS[label],
                value,
                page_number,
                text,
                references,
                uncertainties,
            )

    extracted_lines = [
        ExtractedLine(
            line_number=number,
            product_code=_value(fields, "product_code"),
            description=_value(fields, "description"),
            quantity=_value(fields, "quantity"),
            unit=_value(fields, "unit"),
            unit_price=_value(fields, "unit_price"),
            line_total=_value(fields, "line_total"),
        )
        for number, fields in sorted(lines.items())
    ]
    return ExtractedDocument(
        document_type=document_type,
        document_number=_value(slots, "document_number"),
        supplier_name=_value(slots, "supplier_name"),
        supplier_code=_value(slots, "supplier_code"),
        purchase_order_number=_value(slots, "purchase_order_number"),
        document_date=_value(slots, "document_date"),
        currency=_value(slots, "currency"),
        lines=extracted_lines,
        net_amount=_value(slots, "net_amount"),
        tax_rate_percent=_value(slots, "tax_rate_percent"),
        tax_amount=_value(slots, "tax_amount"),
        amount_due=_value(slots, "amount_due"),
        uncertainties=uncertainties,
        source_references=references,
    )


def _document_type(rows: list[tuple[int, str]]) -> tuple[DocumentType | None, bool]:
    found: list[DocumentType] = []
    for _page, text in rows:
        kind = _HEADINGS.get(text.upper())
        if kind is not None and kind not in found:
            found.append(kind)
    if not found:
        return None, False
    return found[0], len(found) > 1


def _put(
    slots: dict[str, _Slot],
    key: str,
    raw: str,
    page_number: int,
    snippet: str,
    references: list[SourceSnippet],
    uncertainties: list[str],
) -> None:
    slot = slots.setdefault(key, _Slot())
    if slot.conflict:
        return
    value = None if raw.strip().upper() == _NOT_STATED else raw.strip()
    if not slot.seen:
        slot.seen = True
        slot.value = value
        references.append(
            SourceSnippet(field=key, page_number=page_number, snippet=snippet[:_SNIPPET_LIMIT])
        )
        if value is None:
            uncertainties.append(f"{key} is not stated")
        return
    if slot.value != value:
        slot.value = None
        slot.conflict = True
        uncertainties.append(f"{key} is contradictory and was left empty")


def _value(slots: dict[str, _Slot], key: str) -> str | None:
    slot = slots.get(key)
    if slot is None or slot.conflict:
        return None
    return slot.value
