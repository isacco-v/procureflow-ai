"""Synthetic procurement scenarios shared by the matcher tests and the dev seed.

Identifiers are stable so a later iteration can generate PDFs from the same keys.
Every scenario is fictional.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.matching.models import (
    DocumentType,
    ReconciliationInput,
    SourceDocument,
    SourceLine,
)


@dataclass(frozen=True)
class SupplierFixture:
    code: str
    name: str


@dataclass(frozen=True)
class LineFixture:
    line_number: int
    product_code: str | None
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True)
class DocumentFixture:
    document_type: DocumentType
    document_number: str
    purchase_order_number: str | None
    currency: str | None
    document_date: date
    lines: tuple[LineFixture, ...]


@dataclass(frozen=True)
class ScenarioFixture:
    reference: str
    title: str
    summary: str
    supplier: SupplierFixture
    documents: tuple[DocumentFixture, ...]


HELIOS = SupplierFixture(code="SUP-HELIOS", name="Helios Building Supplies")
NORTH_QUARRY = SupplierFixture(code="SUP-NORTH-QUARRY", name="North Quarry Aggregates")

_CEMENT = "Portland Cement CEM II 25kg"
_CEMENT_CODE = "CEM-II-25"


def _po(
    number: str,
    issued_on: date,
    line: LineFixture,
    *,
    currency: str = "EUR",
) -> DocumentFixture:
    return DocumentFixture(
        document_type=DocumentType.PURCHASE_ORDER,
        document_number=number,
        purchase_order_number=number,
        currency=currency,
        document_date=issued_on,
        lines=(line,),
    )


def _delivery(
    number: str,
    purchase_order_number: str,
    delivered_on: date,
    line: LineFixture,
) -> DocumentFixture:
    return DocumentFixture(
        document_type=DocumentType.DELIVERY_NOTE,
        document_number=number,
        purchase_order_number=purchase_order_number,
        currency=None,
        document_date=delivered_on,
        lines=(line,),
    )


def _invoice(
    number: str,
    purchase_order_number: str,
    issued_on: date,
    line: LineFixture,
    *,
    currency: str = "EUR",
) -> DocumentFixture:
    return DocumentFixture(
        document_type=DocumentType.INVOICE,
        document_number=number,
        purchase_order_number=purchase_order_number,
        currency=currency,
        document_date=issued_on,
        lines=(line,),
    )


SCENARIO_A = ScenarioFixture(
    reference="CASE-A-CLEAN",
    title="Clean reconciliation",
    summary=(
        "Synthetic. 100 bags ordered, 100 bags delivered, and 100 bags invoiced "
        "at the same unit price."
    ),
    supplier=HELIOS,
    documents=(
        _po(
            "PO-A-100",
            date(2026, 3, 2),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("100"), "BAG", Decimal("4.50"), "EUR"),
        ),
        _delivery(
            "DN-A-100",
            "PO-A-100",
            date(2026, 3, 5),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("100"), "BAG"),
        ),
        _invoice(
            "INV-A-100",
            "PO-A-100",
            date(2026, 3, 7),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("100"), "BAG", Decimal("4.50"), "EUR"),
        ),
    ),
)

SCENARIO_B = ScenarioFixture(
    reference="CASE-B-QUANTITY",
    title="Quantity discrepancy",
    summary=("Synthetic. 100 bags ordered, 80 bags recorded as delivered, and 100 bags invoiced."),
    supplier=HELIOS,
    documents=(
        _po(
            "PO-B-100",
            date(2026, 3, 2),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("100"), "BAG", Decimal("4.50"), "EUR"),
        ),
        _delivery(
            "DN-B-100",
            "PO-B-100",
            date(2026, 3, 5),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("80"), "BAG"),
        ),
        _invoice(
            "INV-B-100",
            "PO-B-100",
            date(2026, 3, 7),
            LineFixture(1, _CEMENT_CODE, _CEMENT, Decimal("100"), "BAG", Decimal("4.50"), "EUR"),
        ),
    ),
)

SCENARIO_C = ScenarioFixture(
    reference="CASE-C-AMBIGUOUS",
    title="Ambiguous product reference",
    summary=(
        "Synthetic. The descriptions may refer to the same cement, but the lines "
        "do not share an authoritative product identifier."
    ),
    supplier=HELIOS,
    documents=(
        _po(
            "PO-C-100",
            date(2026, 4, 1),
            LineFixture(
                1,
                None,
                "Portland Cement CEM II 25kg",
                Decimal("100"),
                "BAG",
                Decimal("4.50"),
                "EUR",
            ),
        ),
        _delivery(
            "DN-C-100",
            "PO-C-100",
            date(2026, 4, 4),
            LineFixture(1, None, "Cement bags 25 kg", Decimal("100"), "BAG"),
        ),
        _invoice(
            "INV-C-100",
            "PO-C-100",
            date(2026, 4, 6),
            LineFixture(1, None, "CEM II/A-LL 25KG", Decimal("100"), "BAG", Decimal("4.50"), "EUR"),
        ),
    ),
)

SCENARIO_D = ScenarioFixture(
    reference="CASE-D-PARTIAL",
    title="Two partial deliveries",
    summary=(
        "Synthetic. 100 tonnes ordered and invoiced, delivered as 80 tonnes and then 20 tonnes."
    ),
    supplier=NORTH_QUARRY,
    documents=(
        _po(
            "PO-D-100",
            date(2026, 5, 4),
            LineFixture(
                1,
                "AGG-20MM",
                "20mm crushed aggregate",
                Decimal("100"),
                "TONNE",
                Decimal("28.75"),
                "EUR",
            ),
        ),
        _delivery(
            "DN-D-080",
            "PO-D-100",
            date(2026, 5, 8),
            LineFixture(1, "AGG-20MM", "20mm crushed aggregate", Decimal("80"), "TONNE"),
        ),
        _delivery(
            "DN-D-020",
            "PO-D-100",
            date(2026, 5, 12),
            LineFixture(1, "AGG-20MM", "20mm crushed aggregate", Decimal("20"), "TONNE"),
        ),
        _invoice(
            "INV-D-100",
            "PO-D-100",
            date(2026, 5, 14),
            LineFixture(
                1,
                "AGG-20MM",
                "20mm crushed aggregate",
                Decimal("100"),
                "TONNE",
                Decimal("28.75"),
                "EUR",
            ),
        ),
    ),
)

SCENARIO_E = ScenarioFixture(
    reference="CASE-E-PRICE",
    title="Unit price mismatch",
    summary=(
        "Synthetic. Quantities agree at 40 pieces. The invoice unit price "
        "is higher than the purchase order."
    ),
    supplier=HELIOS,
    documents=(
        _po(
            "PO-E-100",
            date(2026, 6, 1),
            LineFixture(
                1,
                "TIM-C24-48",
                "C24 structural timber 4.8m",
                Decimal("40"),
                "EACH",
                Decimal("12.50"),
                "EUR",
            ),
        ),
        _delivery(
            "DN-E-100",
            "PO-E-100",
            date(2026, 6, 4),
            LineFixture(1, "TIM-C24-48", "C24 structural timber 4.8m", Decimal("40"), "EACH"),
        ),
        _invoice(
            "INV-E-100",
            "PO-E-100",
            date(2026, 6, 6),
            LineFixture(
                1,
                "TIM-C24-48",
                "C24 structural timber 4.8m",
                Decimal("40"),
                "EACH",
                Decimal("13.75"),
                "EUR",
            ),
        ),
    ),
)

SCENARIOS: tuple[ScenarioFixture, ...] = (
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    SCENARIO_D,
    SCENARIO_E,
)


def scenario_input(scenario: ScenarioFixture) -> ReconciliationInput:
    documents: list[SourceDocument] = []
    lines: list[SourceLine] = []
    for document in scenario.documents:
        documents.append(
            SourceDocument(
                document_type=document.document_type,
                document_number=document.document_number,
                purchase_order_number=document.purchase_order_number,
                currency=document.currency,
            )
        )
        for line in document.lines:
            lines.append(
                SourceLine(
                    document_type=document.document_type,
                    document_number=document.document_number,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    currency=line.currency,
                )
            )
    return ReconciliationInput(documents=documents, lines=lines)
