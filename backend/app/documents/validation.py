"""Validate an extraction before it can become a procurement record.

Arithmetic uses ``Decimal``. A model is not asked to correct a total. Blocking
warnings refuse acceptance. Advisory warnings stay visible and do not invent
the missing value.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.documents.models import (
    ComputedAmounts,
    ExtractedDocument,
    ExtractedLine,
    NormalizedDocument,
    NormalizedLine,
    ValidationResult,
    ValidationWarning,
)
from app.domain.decimals import format_decimal
from app.domain.matching.models import DocumentType

_MONEY = Decimal("0.01")
_QUANTITY = Decimal("0.0001")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SUPPLIER_CODE = re.compile(r"^[A-Z0-9-]{3,64}$")
_CANONICAL_UNITS = {
    "BAG": "BAG",
    "BAGS": "BAG",
    "KG": "KG",
    "KGS": "KG",
    "KILOGRAM": "KG",
    "KILOGRAMS": "KG",
    "TONNE": "TONNE",
    "TONNES": "TONNE",
    "EACH": "EACH",
    "EA": "EACH",
    "PCS": "EACH",
}
_PRICED = {DocumentType.PURCHASE_ORDER, DocumentType.INVOICE}


def validate_extraction(
    document: ExtractedDocument,
    injection_flags: list[str],
) -> ValidationResult:
    warnings: list[ValidationWarning] = []
    for flag in injection_flags:
        warnings.append(
            ValidationWarning(
                code="untrusted_instruction_text",
                severity="advisory",
                message=(
                    f"The page text matched an instruction-like pattern ({flag}). "
                    "It was not applied."
                ),
                field=None,
            )
        )
    for note in document.uncertainties:
        if "contradictory" in note:
            warnings.append(
                ValidationWarning(
                    code="contradictory_field",
                    severity="blocking",
                    message=note,
                    field=note.split(" ", 1)[0],
                )
            )

    document_type = document.document_type
    if document_type is None:
        warnings.append(
            _blocking("missing_document_type", "Document type was not read.", "document_type")
        )

    document_number = _required_text(
        document.document_number, "document_number", "Document number", warnings
    )
    supplier_name = _required_text(
        document.supplier_name, "supplier_name", "Supplier name", warnings
    )
    supplier_code = _supplier_code(document.supplier_code, warnings)
    parsed_date = _date(document.document_date, warnings)
    currency = _currency(document.currency, document_type, warnings)
    purchase_order_number = _optional_text(document.purchase_order_number)
    if (
        document_type is DocumentType.PURCHASE_ORDER
        and document_number
        and not purchase_order_number
    ):
        purchase_order_number = document_number
    if document_type is not DocumentType.PURCHASE_ORDER and purchase_order_number is None:
        warnings.append(
            ValidationWarning(
                code="missing_purchase_order_reference",
                severity="advisory",
                message="No purchase-order reference was read. The matcher will report that.",
                field="purchase_order_number",
            )
        )

    normalized_lines, computed_line_totals, unresolved = _lines(
        document.lines, document_type, currency, warnings
    )
    computed_net = _sum_money(computed_line_totals)
    stated_net = _money_field(document.net_amount, "net_amount", warnings)
    stated_rate = _money_field(document.tax_rate_percent, "tax_rate_percent", warnings)
    stated_tax = _money_field(document.tax_amount, "tax_amount", warnings)
    stated_due = _money_field(document.amount_due, "amount_due", warnings)
    computed_tax = None
    computed_due = None
    if computed_net is not None and stated_rate is not None:
        computed_tax = _money(computed_net * stated_rate / Decimal("100"))
        computed_due = _money(computed_net + computed_tax)
    _compare_money("net_amount", stated_net, computed_net, warnings)
    _compare_money("tax_amount", stated_tax, computed_tax, warnings)
    _compare_money("amount_due", stated_due, computed_due, warnings)

    blocking = any(item.severity == "blocking" for item in warnings)
    normalized = None
    if (
        not blocking
        and document_type is not None
        and document_number is not None
        and supplier_name is not None
        and supplier_code is not None
        and parsed_date is not None
        and normalized_lines
    ):
        normalized = NormalizedDocument(
            document_type=document_type,
            document_number=document_number,
            supplier_name=supplier_name,
            supplier_code=supplier_code,
            purchase_order_number=purchase_order_number,
            document_date=parsed_date.isoformat(),
            currency=currency,
            lines=normalized_lines,
            net_amount=None if stated_net is None else format_decimal(stated_net),
            tax_rate_percent=None if stated_rate is None else format_decimal(stated_rate),
            tax_amount=None if stated_tax is None else format_decimal(stated_tax),
            amount_due=None if stated_due is None else format_decimal(stated_due),
            unresolved_product_lines=unresolved,
        )
    return ValidationResult(
        status="blocked" if blocking else "ready",
        blocking=blocking,
        warnings=warnings,
        normalized=normalized,
        computed=ComputedAmounts(
            line_totals=[
                None if item is None else format_decimal(item) for item in computed_line_totals
            ],
            net_amount=None if computed_net is None else format_decimal(computed_net),
            tax_amount=None if computed_tax is None else format_decimal(computed_tax),
            amount_due=None if computed_due is None else format_decimal(computed_due),
        ),
    )


def canonical_unit(value: str) -> str | None:
    token = value.strip().upper()
    return _CANONICAL_UNITS.get(token)


def _lines(
    lines: list[ExtractedLine],
    document_type: DocumentType | None,
    currency: str | None,
    warnings: list[ValidationWarning],
) -> tuple[list[NormalizedLine], list[Decimal | None], list[int]]:
    del currency
    if not lines:
        warnings.append(_blocking("missing_lines", "No line items were read.", "lines"))
        return [], [], []
    seen: set[int] = set()
    normalized: list[NormalizedLine] = []
    totals: list[Decimal | None] = []
    unresolved: list[int] = []
    priced = document_type in _PRICED
    for line in lines:
        number = line.line_number
        if number is None or number < 1:
            warnings.append(
                _blocking("invalid_line_number", "A line number is missing.", "line_number")
            )
            continue
        if number in seen:
            warnings.append(
                _blocking("duplicate_line_number", f"Line {number} is repeated.", "line_number")
            )
            continue
        seen.add(number)
        description = _optional_text(line.description)
        if description is None:
            warnings.append(
                _blocking(
                    "missing_description", f"Line {number} has no description.", "description"
                )
            )
            continue
        quantity = _quantity(line.quantity, number, warnings)
        unit = _unit(line.unit, number, warnings)
        unit_price = _money_field(line.unit_price, f"lines.{number}.unit_price", warnings)
        stated_total = _money_field(line.line_total, f"lines.{number}.line_total", warnings)
        if priced and unit_price is None:
            warnings.append(
                _blocking(
                    "missing_unit_price",
                    f"Line {number} has no unit price.",
                    "unit_price",
                )
            )
        if not priced and unit_price is not None:
            warnings.append(
                ValidationWarning(
                    code="delivery_price_not_authoritative",
                    severity="advisory",
                    message=(
                        f"Line {number} states a unit price. Delivery lines do not store a price, "
                        "and this value is not written to the delivery record."
                    ),
                    field="unit_price",
                )
            )
        computed = None
        if quantity is not None and unit_price is not None:
            computed = _money(quantity * unit_price)
            _compare_money(f"lines.{number}.line_total", stated_total, computed, warnings)
        product_code = _optional_text(line.product_code)
        if product_code is None:
            unresolved.append(number)
            warnings.append(
                ValidationWarning(
                    code="unresolved_product_identity",
                    severity="advisory",
                    message=(
                        f"Line {number} has no product code. "
                        "The description is not treated as identity."
                    ),
                    field="product_code",
                )
            )
        if description is None or quantity is None or unit is None:
            continue
        if priced and unit_price is None:
            continue
        normalized.append(
            NormalizedLine(
                line_number=number,
                product_code=product_code,
                description=description,
                quantity=format_decimal(quantity),
                unit=unit,
                unit_price=None if unit_price is None else format_decimal(unit_price),
                line_total=None if stated_total is None else format_decimal(stated_total),
            )
        )
        totals.append(computed)
    return normalized, totals, unresolved


def _required_text(
    value: str | None,
    field: str,
    label: str,
    warnings: list[ValidationWarning],
) -> str | None:
    text = _optional_text(value)
    if text is None:
        warnings.append(_blocking(f"missing_{field}", f"{label} was not read.", field))
    return text


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text or None


def _supplier_code(value: str | None, warnings: list[ValidationWarning]) -> str | None:
    text = _optional_text(value)
    if text is None:
        warnings.append(
            _blocking("missing_supplier_code", "Supplier code was not read.", "supplier_code")
        )
        return None
    normalized = text.upper()
    if _SUPPLIER_CODE.fullmatch(normalized) is None:
        warnings.append(
            _blocking("invalid_supplier_code", "Supplier code is not usable.", "supplier_code")
        )
        return None
    return normalized


def _date(value: str | None, warnings: list[ValidationWarning]) -> date | None:
    text = _optional_text(value)
    if text is None:
        warnings.append(
            _blocking("missing_document_date", "Document date was not read.", "document_date")
        )
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for pattern in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    warnings.append(
        _blocking(
            "invalid_document_date", "Document date could not be normalized.", "document_date"
        )
    )
    return None


def _currency(
    value: str | None,
    document_type: DocumentType | None,
    warnings: list[ValidationWarning],
) -> str | None:
    text = _optional_text(value)
    if text is None:
        if document_type in _PRICED:
            warnings.append(_blocking("missing_currency", "Currency was not read.", "currency"))
        return None
    normalized = text.upper()
    if _CURRENCY.fullmatch(normalized) is None:
        warnings.append(
            _blocking("invalid_currency", "Currency must be a three-letter code.", "currency")
        )
        return None
    return normalized


def _quantity(
    value: str | None,
    line_number: int,
    warnings: list[ValidationWarning],
) -> Decimal | None:
    parsed = _decimal_field(value, f"lines.{line_number}.quantity", warnings)
    if value is not None and _optional_text(value) is not None and parsed is None:
        return None
    if parsed is None:
        warnings.append(
            _blocking("missing_quantity", f"Line {line_number} has no quantity.", "quantity")
        )
        return None
    if parsed <= 0:
        warnings.append(
            _blocking(
                "invalid_quantity", f"Line {line_number} quantity must be positive.", "quantity"
            )
        )
        return None
    if parsed != parsed.quantize(_QUANTITY):
        warnings.append(
            _blocking(
                "excessive_precision",
                f"Line {line_number} quantity has more than four decimal places.",
                "quantity",
            )
        )
        return None
    return parsed


def _unit(value: str | None, line_number: int, warnings: list[ValidationWarning]) -> str | None:
    text = _optional_text(value)
    if text is None:
        warnings.append(_blocking("missing_unit", f"Line {line_number} has no unit.", "unit"))
        return None
    canonical = canonical_unit(text)
    if canonical is None:
        warnings.append(
            ValidationWarning(
                code="unrecognized_unit",
                severity="advisory",
                message=(
                    f"Line {line_number} unit '{text}' has no canonical form "
                    "and is stored uppercased."
                ),
                field="unit",
            )
        )
        return text.upper()
    return canonical


def _money_field(
    value: str | None, field: str, warnings: list[ValidationWarning]
) -> Decimal | None:
    if _optional_text(value) is None:
        return None
    parsed = _decimal_field(value, field, warnings)
    if parsed is None:
        return None
    quantum = _MONEY if "quantity" not in field else _QUANTITY
    if field.endswith("tax_rate_percent"):
        quantum = _MONEY
    if parsed != parsed.quantize(Decimal("0.0001")):
        warnings.append(
            _blocking("excessive_precision", f"{field} has more than four decimal places.", field)
        )
        return None
    if parsed < 0:
        warnings.append(_blocking("invalid_decimal", f"{field} cannot be negative.", field))
        return None
    del quantum
    return parsed


def _decimal_field(
    value: str | None, field: str, warnings: list[ValidationWarning]
) -> Decimal | None:
    text = _optional_text(value)
    if text is None:
        return None
    if isinstance(value, float):
        warnings.append(_blocking("invalid_decimal", f"{field} must not be a float.", field))
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        warnings.append(_blocking("invalid_decimal", f"{field} is not a decimal value.", field))
        return None
    if not parsed.is_finite():
        warnings.append(_blocking("invalid_decimal", f"{field} is not a finite decimal.", field))
        return None
    return parsed


def _compare_money(
    field: str,
    stated: Decimal | None,
    computed: Decimal | None,
    warnings: list[ValidationWarning],
) -> None:
    if stated is None or computed is None:
        return
    if stated != computed:
        warnings.append(
            _blocking(
                "arithmetic_mismatch",
                (
                    f"{field} states {format_decimal(stated)} but quantity, price, and tax "
                    f"recompute to {format_decimal(computed)}. The stated figure was not replaced."
                ),
                field,
            )
        )


def _sum_money(values: list[Decimal | None]) -> Decimal | None:
    present = [item for item in values if item is not None]
    if not present:
        return None
    return _money(sum(present, Decimal("0")))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY)


def _blocking(code: str, message: str, field: str) -> ValidationWarning:
    return ValidationWarning(code=code, severity="blocking", message=message, field=field)
