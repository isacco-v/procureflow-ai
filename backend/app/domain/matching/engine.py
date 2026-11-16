"""Pure three-way matching.

The function ``reconcile`` compares purchase-order, delivery-note, and invoice
lines. It does not read a database, call a model, or inspect the clock.

Lines align only on an authoritative product code. Descriptions are evidence
for a reviewer, including when they look alike. Quantities and prices use
``Decimal``. Mixed units or currencies are reported and are not subtracted
or converted.
"""

import re
from collections import defaultdict
from decimal import Decimal

from app.domain.decimals import format_decimal
from app.domain.matching.models import (
    DocumentType,
    Finding,
    FindingCode,
    MatchConfig,
    MatchStatus,
    ReconciliationInput,
    ReconciliationInputError,
    ReconciliationReport,
    SourceDocument,
    SourceLine,
    SourceReference,
)

ENGINE_VERSION = "1"

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PRICED_TYPES = {DocumentType.PURCHASE_ORDER, DocumentType.INVOICE}
_DOCUMENT_ORDER = {
    DocumentType.PURCHASE_ORDER: 0,
    DocumentType.DELIVERY_NOTE: 1,
    DocumentType.INVOICE: 2,
}
_STATUS_RANK = {
    MatchStatus.MATCHED: 0,
    MatchStatus.EXCEPTION: 1,
    MatchStatus.NEEDS_REVIEW: 2,
}


def prepare_input(data: ReconciliationInput) -> ReconciliationInput:
    """Normalize records and reject a shape the engine cannot compare."""

    documents = [_normalize_document(document) for document in data.documents]
    lines = [_normalize_line(line) for line in data.lines]
    _validate_shape(documents, lines)
    return ReconciliationInput(documents=documents, lines=lines)


def reconcile(
    data: ReconciliationInput,
    config: MatchConfig | None = None,
) -> ReconciliationReport:
    """Return a deterministic reconciliation report for ``data``."""

    settings = config or MatchConfig()
    prepared = prepare_input(data)
    documents = prepared.documents
    lines = prepared.lines

    findings: list[Finding] = []
    purchase_orders = [
        document for document in documents if document.document_type is DocumentType.PURCHASE_ORDER
    ]
    purchase_order = purchase_orders[0] if purchase_orders else None
    if purchase_order is None:
        findings.append(
            _finding(
                FindingCode.MISSING_PURCHASE_ORDER,
                MatchStatus.EXCEPTION,
                "The case has no purchase order, so ordered quantities are zero.",
                references=_document_references(documents),
            )
        )
    findings.extend(_reference_findings(documents, purchase_order))

    if not lines:
        findings.append(
            _finding(
                FindingCode.NO_LINES,
                MatchStatus.NEEDS_REVIEW,
                "The case has no commercial lines to reconcile.",
                references=_document_references(documents),
            )
        )
    else:
        coded: dict[str, list[SourceLine]] = defaultdict(list)
        uncoded: list[SourceLine] = []
        for line in lines:
            if line.product_code is None:
                uncoded.append(line)
            else:
                coded[line.product_code].append(line)
        documents_by_key = {
            (document.document_type, document.document_number): document for document in documents
        }
        for product_code in sorted(coded):
            findings.extend(
                _reconcile_product(
                    product_code,
                    coded[product_code],
                    documents_by_key,
                    settings,
                )
            )
        if uncoded:
            findings.append(_uncertain_mapping(uncoded))

    ordered = sorted(findings, key=_finding_sort_key)
    return ReconciliationReport(status=_rollup(ordered), findings=ordered)


def _normalize_document(document: SourceDocument) -> SourceDocument:
    number = document.document_number.strip()
    if not number:
        raise ReconciliationInputError("Document number is empty.")
    cited = document.purchase_order_number.strip() if document.purchase_order_number else None
    if cited == "":
        cited = None
    return document.model_copy(
        update={
            "document_number": number,
            "purchase_order_number": cited,
            "currency": _normalize_currency(document.currency),
        }
    )


def _normalize_line(line: SourceLine) -> SourceLine:
    number = line.document_number.strip()
    description = line.description.strip()
    unit = line.unit.strip()
    if not number:
        raise ReconciliationInputError("Line document number is empty.")
    if line.line_number < 1:
        raise ReconciliationInputError("Line number must be positive.")
    if not description:
        raise ReconciliationInputError("Line description is empty.")
    if not unit:
        raise ReconciliationInputError("Line unit is empty.")
    if line.quantity <= 0:
        raise ReconciliationInputError("Quantity must be positive.")
    if line.unit_price is not None and line.unit_price < 0:
        raise ReconciliationInputError("Unit price must be zero or positive.")
    product_code = line.product_code.strip() if line.product_code else None
    if product_code == "":
        product_code = None
    return line.model_copy(
        update={
            "document_number": number,
            "description": description,
            "unit": unit,
            "product_code": product_code,
            "currency": _normalize_currency(line.currency),
        }
    )


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    currency = value.strip().upper()
    if currency == "":
        return None
    if _CURRENCY.fullmatch(currency) is None:
        raise ReconciliationInputError("Currency must be a three-letter ISO code.")
    return currency


def _validate_shape(documents: list[SourceDocument], lines: list[SourceLine]) -> None:
    keys = [(document.document_type, document.document_number) for document in documents]
    if len(keys) != len(set(keys)):
        raise ReconciliationInputError("Document numbers must be unique for each document type.")
    purchase_orders = [key for key in keys if key[0] is DocumentType.PURCHASE_ORDER]
    if len(purchase_orders) > 1:
        raise ReconciliationInputError("A case can have only one purchase order.")
    known = set(keys)
    seen_lines: set[tuple[DocumentType, str, int]] = set()
    for line in lines:
        identity = (line.document_type, line.document_number, line.line_number)
        if identity in seen_lines:
            raise ReconciliationInputError(
                f"Duplicate line {line.line_number} on {line.document_number}."
            )
        seen_lines.add(identity)
        if (line.document_type, line.document_number) not in known:
            raise ReconciliationInputError(
                f"Line {line.line_number} cites unknown document {line.document_number}."
            )


def _reference_findings(
    documents: list[SourceDocument],
    purchase_order: SourceDocument | None,
) -> list[Finding]:
    expected = None if purchase_order is None else purchase_order.document_number
    findings: list[Finding] = []
    linked = [
        document
        for document in documents
        if document.document_type is not DocumentType.PURCHASE_ORDER
    ]
    for document in sorted(
        linked, key=lambda item: (item.document_type.value, item.document_number)
    ):
        cited = document.purchase_order_number
        reference = _document_references([document])
        label = _document_label(document)
        if cited is None:
            findings.append(
                _finding(
                    FindingCode.MISSING_REFERENCE,
                    MatchStatus.EXCEPTION,
                    f"{label} does not cite a purchase order.",
                    references=reference,
                )
            )
        elif expected is None or cited != expected:
            target = "no purchase order on the case" if expected is None else expected
            findings.append(
                _finding(
                    FindingCode.REFERENCE_MISMATCH,
                    MatchStatus.EXCEPTION,
                    f"{label} cites purchase order {cited}, which does not match {target}.",
                    references=reference,
                )
            )
    return findings


def _reconcile_product(
    product_code: str,
    lines: list[SourceLine],
    documents_by_key: dict[tuple[DocumentType, str], SourceDocument],
    config: MatchConfig,
) -> list[Finding]:
    references = _line_references(lines)
    display_unit = _display_unit(lines)
    ordered = _quantity(lines, DocumentType.PURCHASE_ORDER)
    delivered = _quantity(lines, DocumentType.DELIVERY_NOTE)
    invoiced = _quantity(lines, DocumentType.INVOICE)
    units = sorted({_unit_key(line.unit) for line in lines})
    if len(units) > 1:
        listed = ", ".join(units)
        return [
            _finding(
                FindingCode.UNIT_MISMATCH,
                MatchStatus.NEEDS_REVIEW,
                (
                    f"Product {product_code} uses more than one unit ({listed}). "
                    "Quantities and prices were not compared."
                ),
                product_code=product_code,
                unit=None,
                ordered_quantity=ordered,
                delivered_quantity=delivered,
                invoiced_quantity=invoiced,
                references=references,
            )
        ]

    priced = [line for line in lines if line.document_type in _PRICED_TYPES]
    currencies = _effective_currencies(priced, documents_by_key)
    currency_findings: list[Finding] = []
    prices_comparable = True
    quantity_gap = Decimal("0") if _quantities_agree(ordered, delivered, invoiced, config) else None
    if any(currency is None for currency in currencies):
        prices_comparable = False
        currency_findings.append(
            _finding(
                FindingCode.MISSING_CURRENCY,
                MatchStatus.NEEDS_REVIEW,
                (
                    f"Product {product_code} has a priced line without a currency. "
                    "Prices were not compared."
                ),
                product_code=product_code,
                unit=display_unit,
                ordered_quantity=ordered,
                delivered_quantity=delivered,
                invoiced_quantity=invoiced,
                quantity_difference=quantity_gap,
                references=references,
            )
        )
    distinct_currencies = sorted({currency for currency in currencies if currency is not None})
    if len(distinct_currencies) > 1:
        prices_comparable = False
        listed = ", ".join(distinct_currencies)
        currency_findings.append(
            _finding(
                FindingCode.CURRENCY_MISMATCH,
                MatchStatus.EXCEPTION,
                (
                    f"Product {product_code} uses more than one currency ({listed}). "
                    "Prices were not compared."
                ),
                product_code=product_code,
                unit=display_unit,
                ordered_quantity=ordered,
                delivered_quantity=delivered,
                invoiced_quantity=invoiced,
                quantity_difference=quantity_gap,
                references=references,
            )
        )

    po_prices = _prices(lines, DocumentType.PURCHASE_ORDER)
    invoice_prices = _prices(lines, DocumentType.INVOICE)
    price_findings: list[Finding] = []
    matched_price: tuple[Decimal, Decimal, str] | None = None
    if prices_comparable:
        price_findings, matched_price = _price_findings(
            product_code,
            lines,
            display_unit,
            ordered,
            delivered,
            invoiced,
            po_prices,
            invoice_prices,
            distinct_currencies[0] if len(distinct_currencies) == 1 else None,
            config,
            references,
        )

    quantity_findings = _quantity_findings(
        product_code,
        display_unit,
        ordered,
        delivered,
        invoiced,
        matched_price,
        config,
        references,
    )
    if (
        not quantity_findings
        and not price_findings
        and not currency_findings
        and matched_price is not None
    ):
        po_price, invoice_price, currency = matched_price
        return [
            _finding(
                FindingCode.LINE_RECONCILED,
                MatchStatus.MATCHED,
                (
                    f"Ordered, delivered, and invoiced quantities and the unit price "
                    f"agree for product {product_code}."
                ),
                product_code=product_code,
                unit=display_unit,
                currency=currency,
                ordered_quantity=ordered,
                delivered_quantity=delivered,
                invoiced_quantity=invoiced,
                quantity_difference=Decimal("0"),
                purchase_order_unit_price=po_price,
                invoice_unit_price=invoice_price,
                price_difference=Decimal("0"),
                references=references,
            )
        ]
    return [*currency_findings, *quantity_findings, *price_findings]


def _price_findings(
    product_code: str,
    lines: list[SourceLine],
    unit: str,
    ordered: Decimal,
    delivered: Decimal,
    invoiced: Decimal,
    po_prices: list[Decimal],
    invoice_prices: list[Decimal],
    currency: str | None,
    config: MatchConfig,
    references: list[SourceReference],
) -> tuple[list[Finding], tuple[Decimal, Decimal, str] | None]:
    findings: list[Finding] = []
    po_lines = [line for line in lines if line.document_type is DocumentType.PURCHASE_ORDER]
    invoice_lines = [line for line in lines if line.document_type is DocumentType.INVOICE]
    if any(line.unit_price is None for line in po_lines) or (
        invoice_lines and any(line.unit_price is None for line in invoice_lines)
    ):
        findings.append(
            _quantity_context(
                FindingCode.MISSING_UNIT_PRICE,
                MatchStatus.NEEDS_REVIEW,
                f"Product {product_code} is missing a unit price. Prices were not compared.",
                product_code,
                unit,
                currency,
                ordered,
                delivered,
                invoiced,
                references,
            )
        )
        return findings, None
    distinct_po = _unique(po_prices)
    distinct_invoice = _unique(invoice_prices)
    if len(distinct_po) > 1 or len(distinct_invoice) > 1:
        findings.append(
            _quantity_context(
                FindingCode.INCONSISTENT_UNIT_PRICE,
                MatchStatus.NEEDS_REVIEW,
                (
                    f"Product {product_code} has more than one unit price on the same "
                    "document side. Prices were not compared."
                ),
                product_code,
                unit,
                currency,
                ordered,
                delivered,
                invoiced,
                references,
            )
        )
        return findings, None
    if len(distinct_po) == 1 and len(distinct_invoice) == 1 and currency is not None:
        po_price = distinct_po[0]
        invoice_price = distinct_invoice[0]
        if abs(invoice_price - po_price) > config.price_tolerance:
            difference = invoice_price - po_price
            findings.append(
                _finding(
                    FindingCode.PRICE_MISMATCH,
                    MatchStatus.EXCEPTION,
                    (
                        f"Invoice unit price {format_decimal(invoice_price)} {currency} differs "
                        f"from purchase order unit price {format_decimal(po_price)} {currency} "
                        f"for product {product_code}."
                    ),
                    product_code=product_code,
                    unit=unit,
                    currency=currency,
                    ordered_quantity=ordered,
                    delivered_quantity=delivered,
                    invoiced_quantity=invoiced,
                    quantity_difference=Decimal("0")
                    if _quantities_agree(ordered, delivered, invoiced, config)
                    else None,
                    purchase_order_unit_price=po_price,
                    invoice_unit_price=invoice_price,
                    price_difference=difference,
                    references=references,
                )
            )
            return findings, None
        return findings, (po_price, invoice_price, currency)
    return findings, None


def _quantity_findings(
    product_code: str,
    unit: str,
    ordered: Decimal,
    delivered: Decimal,
    invoiced: Decimal,
    matched_price: tuple[Decimal, Decimal, str] | None,
    config: MatchConfig,
    references: list[SourceReference],
) -> list[Finding]:
    if _quantities_agree(ordered, delivered, invoiced, config):
        return []
    price_kwargs: dict[str, Decimal | str | None] = {}
    if matched_price is not None:
        po_price, invoice_price, currency = matched_price
        price_kwargs = {
            "currency": currency,
            "purchase_order_unit_price": po_price,
            "invoice_unit_price": invoice_price,
            "price_difference": Decimal("0"),
        }
    comparisons = (
        (
            ordered,
            delivered,
            FindingCode.ORDERED_NOT_DELIVERED,
            FindingCode.DELIVERED_NOT_ORDERED,
            "Ordered quantity exceeds recorded deliveries",
            "Delivered quantity exceeds the purchase order",
        ),
        (
            invoiced,
            delivered,
            FindingCode.INVOICED_WITHOUT_DELIVERY,
            FindingCode.DELIVERED_NOT_INVOICED,
            "Invoiced quantity exceeds recorded deliveries",
            "Delivered quantity exceeds the invoice",
        ),
        (
            invoiced,
            ordered,
            FindingCode.INVOICED_NOT_ORDERED,
            FindingCode.ORDERED_NOT_INVOICED,
            "Invoiced quantity exceeds the purchase order",
            "Ordered quantity exceeds the invoice",
        ),
    )
    findings: list[Finding] = []
    for left, right, over_code, under_code, over_text, under_text in comparisons:
        if not _material(left, right, config.quantity_tolerance):
            continue
        if left > right:
            code = over_code
            difference = left - right
            text = over_text
        else:
            code = under_code
            difference = right - left
            text = under_text
        findings.append(
            _finding(
                code,
                MatchStatus.EXCEPTION,
                (f"{text} by {format_decimal(difference)} {unit} for product {product_code}."),
                product_code=product_code,
                unit=unit,
                ordered_quantity=ordered,
                delivered_quantity=delivered,
                invoiced_quantity=invoiced,
                quantity_difference=difference,
                references=references,
                **price_kwargs,
            )
        )
    return findings


def _uncertain_mapping(lines: list[SourceLine]) -> Finding:
    descriptions = []
    for line in sorted(lines, key=_line_sort_key):
        label = f"{line.document_number} line {line.line_number}: {line.description}"
        if label not in descriptions:
            descriptions.append(label)
    listed = "; ".join(descriptions)
    count = len(lines)
    noun = "line" if count == 1 else "lines"
    return _finding(
        FindingCode.UNCERTAIN_PRODUCT_MAPPING,
        MatchStatus.NEEDS_REVIEW,
        (
            f"{count} {noun} have no authoritative product identifier, so they were not "
            f"matched to each other or to coded products. Descriptions: {listed}."
        ),
        references=_line_references(lines),
    )


def _quantities_agree(
    ordered: Decimal,
    delivered: Decimal,
    invoiced: Decimal,
    config: MatchConfig,
) -> bool:
    return (
        not _material(ordered, delivered, config.quantity_tolerance)
        and not _material(delivered, invoiced, config.quantity_tolerance)
        and not _material(ordered, invoiced, config.quantity_tolerance)
    )


def _material(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) > tolerance


def _quantity(lines: list[SourceLine], document_type: DocumentType) -> Decimal:
    total = Decimal("0")
    for line in lines:
        if line.document_type is document_type:
            total += line.quantity
    return total


def _prices(lines: list[SourceLine], document_type: DocumentType) -> list[Decimal]:
    return [
        line.unit_price
        for line in lines
        if line.document_type is document_type and line.unit_price is not None
    ]


def _unique(values: list[Decimal]) -> list[Decimal]:
    distinct: list[Decimal] = []
    for value in values:
        if all(value != existing for existing in distinct):
            distinct.append(value)
    return distinct


def _effective_currencies(
    lines: list[SourceLine],
    documents_by_key: dict[tuple[DocumentType, str], SourceDocument],
) -> list[str | None]:
    currencies: list[str | None] = []
    for line in lines:
        document = documents_by_key[(line.document_type, line.document_number)]
        chosen = line.currency or document.currency
        header = document.currency
        currencies.append(chosen)
        if line.currency is not None and header is not None and line.currency != header:
            currencies.append(header)
    return currencies


def _display_unit(lines: list[SourceLine]) -> str:
    for document_type in (
        DocumentType.PURCHASE_ORDER,
        DocumentType.DELIVERY_NOTE,
        DocumentType.INVOICE,
    ):
        for line in sorted(lines, key=_line_sort_key):
            if line.document_type is document_type:
                return line.unit
    return lines[0].unit


def _unit_key(unit: str) -> str:
    return unit.casefold()


def _document_label(document: SourceDocument) -> str:
    names = {
        DocumentType.PURCHASE_ORDER: "Purchase order",
        DocumentType.DELIVERY_NOTE: "Delivery note",
        DocumentType.INVOICE: "Invoice",
    }
    return f"{names[document.document_type]} {document.document_number}"


def _document_references(documents: list[SourceDocument]) -> list[SourceReference]:
    return [
        SourceReference(
            document_type=document.document_type, document_number=document.document_number
        )
        for document in sorted(
            documents,
            key=lambda item: (_DOCUMENT_ORDER[item.document_type], item.document_number),
        )
    ]


def _line_references(lines: list[SourceLine]) -> list[SourceReference]:
    return [
        SourceReference(
            document_type=line.document_type,
            document_number=line.document_number,
            line_number=line.line_number,
        )
        for line in sorted(lines, key=_line_sort_key)
    ]


def _line_sort_key(line: SourceLine) -> tuple[int, str, int]:
    return (_DOCUMENT_ORDER[line.document_type], line.document_number, line.line_number)


def _finding_sort_key(finding: Finding) -> tuple[str, str, str]:
    return (finding.code.value, finding.product_code or "", finding.message)


def _rollup(findings: list[Finding]) -> MatchStatus:
    if not findings:
        return MatchStatus.NEEDS_REVIEW
    return max(findings, key=lambda finding: _STATUS_RANK[finding.status]).status


def _quantity_context(
    code: FindingCode,
    status: MatchStatus,
    message: str,
    product_code: str,
    unit: str,
    currency: str | None,
    ordered: Decimal,
    delivered: Decimal,
    invoiced: Decimal,
    references: list[SourceReference],
) -> Finding:
    return _finding(
        code,
        status,
        message,
        product_code=product_code,
        unit=unit,
        currency=currency,
        ordered_quantity=ordered,
        delivered_quantity=delivered,
        invoiced_quantity=invoiced,
        references=references,
    )


def _finding(
    code: FindingCode,
    status: MatchStatus,
    message: str,
    *,
    product_code: str | None = None,
    unit: str | None = None,
    currency: str | None = None,
    ordered_quantity: Decimal | None = None,
    delivered_quantity: Decimal | None = None,
    invoiced_quantity: Decimal | None = None,
    quantity_difference: Decimal | None = None,
    purchase_order_unit_price: Decimal | None = None,
    invoice_unit_price: Decimal | None = None,
    price_difference: Decimal | None = None,
    references: list[SourceReference] | None = None,
) -> Finding:
    return Finding(
        code=code,
        status=status,
        product_code=product_code,
        message=message,
        unit=unit,
        currency=currency,
        ordered_quantity=ordered_quantity,
        delivered_quantity=delivered_quantity,
        invoiced_quantity=invoiced_quantity,
        quantity_difference=quantity_difference,
        purchase_order_unit_price=purchase_order_unit_price,
        invoice_unit_price=invoice_unit_price,
        price_difference=price_difference,
        source_references=references or [],
    )
