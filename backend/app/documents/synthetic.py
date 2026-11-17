"""Synthetic construction PDFs and the ground-truth catalog.

The PDFs are fictional. File names and content hashes identify the files on
disk for the evaluation harness. They are not inputs to an extractor.
"""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pymupdf

from app.domain.matching.models import DocumentType
from app.domain.scenarios import SCENARIOS, DocumentFixture, ScenarioFixture, SupplierFixture

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PDF_DIR = FIXTURES_DIR / "pdfs"
CATALOG_PATH = FIXTURES_DIR / "ground_truth.json"

_MONEY = Decimal("0.01")
_VAT_RATE = Decimal("21")
_ADDRESSES = {
    "SUP-HELIOS": "14 Quarry Lane, Rotterdam",
    "SUP-NORTH-QUARRY": "8 Pit Road, Maastricht",
}
_LAYOUT_STYLE = {
    "works_order": {"origin": (48, 72), "title": 18, "body": 10, "bar": (0.12, 0.27, 0.42)},
    "goods_received": {"origin": (70, 86), "title": 15, "body": 10, "bar": (0.18, 0.38, 0.28)},
    "delivery_ticket": {"origin": (54, 64), "title": 16, "body": 10, "bar": (0.42, 0.28, 0.12)},
    "tax_invoice": {"origin": (46, 78), "title": 17, "body": 10, "bar": (0.22, 0.18, 0.38)},
}


def layout_for(document: DocumentFixture) -> str:
    if document.document_type is DocumentType.PURCHASE_ORDER:
        return "works_order"
    if document.document_type is DocumentType.DELIVERY_NOTE:
        if document.document_number == "DN-D-020":
            return "delivery_ticket"
        return "goods_received"
    return "tax_invoice"


def file_name_for(document: DocumentFixture) -> str:
    return f"{layout_for(document)}-{document.document_number.lower()}.pdf"


def render_pdf(document: DocumentFixture, supplier: SupplierFixture) -> bytes:
    """Draw one fictional PDF. The visible labels are the extraction source."""

    layout = layout_for(document)
    style = _LAYOUT_STYLE[layout]
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    red, green, blue = style["bar"]
    page.draw_rect(pymupdf.Rect(0, 0, 595, 28), fill=(red, green, blue), color=(red, green, blue))
    if layout == "tax_invoice":
        page.draw_rect(pymupdf.Rect(32, 40, 563, 810), color=(0.15, 0.15, 0.15))
    elif layout == "goods_received":
        page.draw_rect(pymupdf.Rect(400, 40, 560, 130), color=(0.2, 0.2, 0.2))
    elif layout == "delivery_ticket":
        page.draw_line(pymupdf.Point(40, 40), pymupdf.Point(555, 40))
    x_pos, y_pos = style["origin"]
    for index, line in enumerate(text_lines(document, supplier)):
        size = style["title"] if index == 0 else style["body"]
        page.insert_text((x_pos, y_pos), line, fontsize=size, fontname="helv")
        y_pos += 20 if index == 0 else 14
    pdf.set_metadata(
        {
            "title": "Synthetic construction document",
            "author": "ProcureFlow fixture generator",
            "creator": "ProcureFlow fixture generator",
            "producer": "ProcureFlow fixture generator",
        }
    )
    payload = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    # PyMuPDF writes a random trailer ID. Replace it so the same document
    # always hashes to the same bytes. The extractor never reads this trailer.
    return re.sub(
        rb"/ID\s*\[<[^>]+><[^>]+>\]",
        b"/ID[<00000000000000000000000000000000><00000000000000000000000000000000>]",
        payload,
        count=1,
    )


def text_lines(document: DocumentFixture, supplier: SupplierFixture) -> list[str]:
    layout = layout_for(document)
    address = _ADDRESSES[supplier.code]
    priced = document.document_type is not DocumentType.DELIVERY_NOTE
    currency = document.currency if priced else None
    header = _header(layout, document, supplier, address, currency)
    body: list[str] = []
    net = Decimal("0")
    for line in document.lines:
        amount = None
        if priced and line.unit_price is not None:
            amount = _money(line.quantity * line.unit_price)
            net += amount
        if layout == "delivery_ticket":
            code = line.product_code or "NOT STATED"
            body.append(
                f"Item {line.line_number}: code={code}; material={line.description}; "
                f"quantity={_plain(line.quantity)}; unit={line.unit}"
            )
            continue
        body.extend(
            [
                f"Line {line.line_number}",
                f"Product code: {line.product_code or 'NOT STATED'}",
                f"Description: {line.description}",
                f"Quantity: {_plain(line.quantity)}",
                f"Unit of measure: {line.unit}",
                f"Unit price: {_money_text(line.unit_price) if priced else 'NOT STATED'}",
                f"Line amount: {_money_text(amount) if amount is not None else 'NOT STATED'}",
            ]
        )
    totals = _totals(document, net if priced else None)
    return [*header, *body, *totals, "Page 1 of 1"]


def expected_fields(document: DocumentFixture, supplier: SupplierFixture) -> dict[str, object]:
    """Ground-truth fields for one document. Independent of the file name."""

    priced = document.document_type is not DocumentType.DELIVERY_NOTE
    net = Decimal("0")
    lines: list[dict[str, object]] = []
    for line in document.lines:
        amount = None
        if priced and line.unit_price is not None:
            amount = _money(line.quantity * line.unit_price)
            net += amount
        lines.append(
            {
                "line_number": line.line_number,
                "product_code": line.product_code,
                "description": line.description,
                "quantity": _plain(line.quantity),
                "unit": line.unit,
                "unit_price": None
                if not priced or line.unit_price is None
                else _plain(line.unit_price),
                "line_total": None if amount is None else _plain(amount),
            }
        )
    tax_rate = _VAT_RATE if document.document_type is DocumentType.INVOICE else None
    tax = _money(net * tax_rate / Decimal("100")) if tax_rate is not None else None
    due = _money(net + tax) if tax is not None else None
    return {
        "document_type": document.document_type.value,
        "document_number": document.document_number,
        "supplier_name": supplier.name,
        "supplier_code": supplier.code,
        "purchase_order_number": document.purchase_order_number,
        "document_date": document.document_date.isoformat(),
        "currency": document.currency if priced else None,
        "net_amount": None if not priced else _plain(net),
        "tax_rate_percent": None if tax_rate is None else _plain(tax_rate),
        "tax_amount": None if tax is None else _plain(tax),
        "amount_due": None if due is None else _plain(due),
        "lines": lines,
    }


def build_catalog(entries: list[dict[str, object]] | None = None) -> dict[str, object]:
    if entries is None:
        documents: list[dict[str, object]] = []
        for scenario in SCENARIOS:
            for document in scenario.documents:
                documents.append(_catalog_document(scenario, document))
    else:
        documents = entries
    return {
        "dataset": "procureflow-synthetic-documents",
        "version": 1,
        "description": (
            "Fictional construction purchase orders, delivery notes, and invoices "
            "generated from the five ProcureFlow scenarios. Not customer data. "
            "Extractors must read page text. File names and content hashes are "
            "catalog metadata only."
        ),
        "language_model_measured": False,
        "documents": documents,
    }


def write_fixtures(root: Path | None = None) -> dict[str, object]:
    base = FIXTURES_DIR if root is None else root
    pdf_dir = base / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    documents: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        for document in scenario.documents:
            payload = render_pdf(document, scenario.supplier)
            name = file_name_for(document)
            (pdf_dir / name).write_bytes(payload)
            entry = _catalog_document(scenario, document)
            entry["content_sha256"] = hashlib.sha256(payload).hexdigest()
            documents.append(entry)
    catalog = build_catalog(documents)
    (base / "ground_truth.json").write_text(
        json.dumps(catalog, indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog


def load_catalog() -> dict[str, object]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _catalog_document(scenario: ScenarioFixture, document: DocumentFixture) -> dict[str, object]:
    return {
        "file_name": file_name_for(document),
        "layout": layout_for(document),
        "scenario_reference": scenario.reference,
        "content_sha256": None,
        **expected_fields(document, scenario.supplier),
    }


def _header(
    layout: str,
    document: DocumentFixture,
    supplier: SupplierFixture,
    address: str,
    currency: str | None,
) -> list[str]:
    currency_text = currency if currency is not None else "NOT STATED"
    if layout == "works_order":
        return [
            "WORKS ORDER",
            "Buyer copy for construction materials",
            "Synthetic document. Not a customer record.",
            f"Supplier name: {supplier.name}",
            address,
            f"Supplier account: {supplier.code}",
            f"Works order number: {document.document_number}",
            f"Order date: {document.document_date.isoformat()}",
            f"Currency code: {currency_text}",
            f"Site reference: {document.purchase_order_number}",
        ]
    if layout == "goods_received":
        return [
            "GOODS RECEIVED NOTE",
            "Site copy",
            "Synthetic document. Not a customer record.",
            f"Received from: {supplier.name}",
            address,
            f"Account code: {supplier.code}",
            f"Goods received number: {document.document_number}",
            f"Date received: {document.document_date.isoformat()}",
            f"Currency code: {currency_text}",
            f"Order number: {document.purchase_order_number}",
        ]
    if layout == "delivery_ticket":
        return [
            "DELIVERY TICKET",
            "Quarry dispatch copy",
            "Synthetic document. Not a customer record.",
            f"Haulier: {supplier.name}",
            address,
            f"Customer account: {supplier.code}",
            f"Ticket: {document.document_number}",
            f"Dispatch date: {document.document_date.isoformat()}",
            f"Currency code: {currency_text}",
            f"Customer purchase order: {document.purchase_order_number}",
        ]
    return [
        "SUPPLIER TAX INVOICE",
        "Accounts payable",
        "Synthetic document. Not a customer record.",
        f"Supplier name: {supplier.name}",
        address,
        f"Supplier account: {supplier.code}",
        f"Invoice number: {document.document_number}",
        f"Invoice date: {document.document_date.isoformat()}",
        f"Currency code: {currency_text}",
        f"Customer order: {document.purchase_order_number}",
    ]


def _totals(document: DocumentFixture, net: Decimal | None) -> list[str]:
    if document.document_type is DocumentType.INVOICE and net is not None:
        tax = _money(net * _VAT_RATE / Decimal("100"))
        due = _money(net + tax)
        return [
            f"Net amount: {_money_text(net)}",
            f"VAT rate percent: {_plain(_VAT_RATE)}",
            f"VAT amount: {_money_text(tax)}",
            f"Amount due: {_money_text(due)}",
        ]
    if document.document_type is DocumentType.PURCHASE_ORDER and net is not None:
        return [
            f"Net amount: {_money_text(net)}",
            "Tax: NOT STATED",
            "Amount due: NOT STATED",
        ]
    return [
        "Prices are not printed on this note.",
        "Net amount: NOT STATED",
        "Tax: NOT STATED",
        "Amount due: NOT STATED",
    ]


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY)


def _money_text(value: Decimal | None) -> str:
    if value is None:
        return "NOT STATED"
    return f"{_money(value):.2f}"


def main() -> None:
    catalog = write_fixtures()
    documents = catalog["documents"]
    count = len(documents) if isinstance(documents, list) else 0
    print(f"Wrote {count} synthetic PDFs to {PDF_DIR}")


def _plain(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


if __name__ == "__main__":
    main()
