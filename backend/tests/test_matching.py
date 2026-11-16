"""Pure matching-engine tests. They do not open a database or a network connection."""

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app.domain.matching.engine import reconcile
from app.domain.matching.fingerprint import fingerprint_input
from app.domain.matching.models import (
    DocumentType,
    FindingCode,
    MatchConfig,
    MatchStatus,
    ReconciliationInput,
    ReconciliationInputError,
    SourceDocument,
    SourceLine,
)
from app.domain.scenarios import (
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    SCENARIO_D,
    SCENARIO_E,
    scenario_input,
)

_ENGINE_PATH = Path(__file__).resolve().parents[1] / "app" / "domain" / "matching" / "engine.py"


def _line(
    document_type: DocumentType,
    document_number: str,
    *,
    product_code: str | None,
    description: str,
    quantity: str,
    unit: str,
    unit_price: str | None = None,
    currency: str | None = None,
    line_number: int = 1,
) -> SourceLine:
    return SourceLine(
        document_type=document_type,
        document_number=document_number,
        line_number=line_number,
        product_code=product_code,
        description=description,
        quantity=Decimal(quantity),
        unit=unit,
        unit_price=None if unit_price is None else Decimal(unit_price),
        currency=currency,
    )


def _documents(*specs: tuple[DocumentType, str, str | None, str | None]) -> list[SourceDocument]:
    return [
        SourceDocument(
            document_type=document_type,
            document_number=number,
            purchase_order_number=purchase_order_number,
            currency=currency,
        )
        for document_type, number, purchase_order_number, currency in specs
    ]


def _commercial(
    lines: list[SourceLine],
    *,
    purchase_order_number: str = "PO-1",
    delivery_numbers: tuple[str, ...] = ("DN-1",),
    invoice_number: str = "INV-1",
    purchase_order_currency: str = "EUR",
    invoice_currency: str = "EUR",
    delivery_references: dict[str, str | None] | None = None,
) -> ReconciliationInput:
    references = delivery_references or {
        number: purchase_order_number for number in delivery_numbers
    }
    documents = [
        SourceDocument(
            document_type=DocumentType.PURCHASE_ORDER,
            document_number=purchase_order_number,
            purchase_order_number=purchase_order_number,
            currency=purchase_order_currency,
        ),
        *[
            SourceDocument(
                document_type=DocumentType.DELIVERY_NOTE,
                document_number=number,
                purchase_order_number=references[number],
                currency=None,
            )
            for number in delivery_numbers
        ],
        SourceDocument(
            document_type=DocumentType.INVOICE,
            document_number=invoice_number,
            purchase_order_number=purchase_order_number,
            currency=invoice_currency,
        ),
    ]
    return ReconciliationInput(documents=documents, lines=lines)


def _codes(report) -> set[FindingCode]:
    return {finding.code for finding in report.findings}


def test_scenario_a_clean_reconciliation_matches() -> None:
    report = reconcile(scenario_input(SCENARIO_A))

    assert report.status is MatchStatus.MATCHED
    assert _codes(report) == {FindingCode.LINE_RECONCILED}
    finding = report.findings[0]
    assert finding.ordered_quantity == Decimal("100")
    assert finding.delivered_quantity == Decimal("100")
    assert finding.invoiced_quantity == Decimal("100")
    assert finding.quantity_difference == Decimal("0")
    assert finding.price_difference == Decimal("0")
    assert finding.purchase_order_unit_price == Decimal("4.50")
    assert finding.invoice_unit_price == Decimal("4.50")
    assert [reference.document_number for reference in finding.source_references] == [
        "PO-A-100",
        "DN-A-100",
        "INV-A-100",
    ]


def test_scenario_b_reports_invoiced_units_without_delivery() -> None:
    report = reconcile(scenario_input(SCENARIO_B))

    assert report.status is MatchStatus.EXCEPTION
    assert _codes(report) == {
        FindingCode.ORDERED_NOT_DELIVERED,
        FindingCode.INVOICED_WITHOUT_DELIVERY,
    }
    invoiced = next(
        finding
        for finding in report.findings
        if finding.code is FindingCode.INVOICED_WITHOUT_DELIVERY
    )
    assert invoiced.ordered_quantity == Decimal("100")
    assert invoiced.delivered_quantity == Decimal("80")
    assert invoiced.invoiced_quantity == Decimal("100")
    assert invoiced.quantity_difference == Decimal("20")
    assert invoiced.price_difference == Decimal("0")
    assert "INV-B-100" in {reference.document_number for reference in invoiced.source_references}
    assert "DN-B-100" in {reference.document_number for reference in invoiced.source_references}


def test_scenario_c_does_not_merge_similar_descriptions() -> None:
    report = reconcile(scenario_input(SCENARIO_C))

    assert report.status is MatchStatus.NEEDS_REVIEW
    assert _codes(report) == {FindingCode.UNCERTAIN_PRODUCT_MAPPING}
    finding = report.findings[0]
    assert finding.product_code is None
    assert finding.quantity_difference is None
    assert finding.ordered_quantity is None
    assert "Portland Cement CEM II 25kg" in finding.message
    assert "Cement bags 25 kg" in finding.message
    assert "CEM II/A-LL 25KG" in finding.message
    assert "not matched" in finding.message


def test_scenario_d_sums_partial_deliveries() -> None:
    report = reconcile(scenario_input(SCENARIO_D))

    assert report.status is MatchStatus.MATCHED
    finding = report.findings[0]
    assert finding.code is FindingCode.LINE_RECONCILED
    assert finding.ordered_quantity == Decimal("100")
    assert finding.delivered_quantity == Decimal("100")
    assert finding.invoiced_quantity == Decimal("100")
    assert {reference.document_number for reference in finding.source_references} >= {
        "DN-D-080",
        "DN-D-020",
    }


def test_scenario_e_reports_the_unit_price_gap() -> None:
    report = reconcile(scenario_input(SCENARIO_E))

    assert report.status is MatchStatus.EXCEPTION
    assert _codes(report) == {FindingCode.PRICE_MISMATCH}
    finding = report.findings[0]
    assert finding.ordered_quantity == Decimal("40")
    assert finding.delivered_quantity == Decimal("40")
    assert finding.invoiced_quantity == Decimal("40")
    assert finding.quantity_difference == Decimal("0")
    assert finding.purchase_order_unit_price == Decimal("12.50")
    assert finding.invoice_unit_price == Decimal("13.75")
    assert finding.price_difference == Decimal("1.25")
    assert finding.currency == "EUR"


def test_identical_descriptions_with_different_codes_stay_separate() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="CEM-II-25",
            description="Portland cement",
            quantity="10",
            unit="BAG",
            unit_price="4",
            currency="EUR",
        ),
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="CEM-I-25",
            description="Portland cement",
            quantity="5",
            unit="BAG",
            unit_price="4",
            currency="EUR",
            line_number=2,
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="CEM-II-25",
            description="Portland cement",
            quantity="10",
            unit="BAG",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="CEM-I-25",
            description="Portland cement",
            quantity="5",
            unit="BAG",
            line_number=2,
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="CEM-II-25",
            description="Portland cement",
            quantity="10",
            unit="BAG",
            unit_price="4",
            currency="EUR",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="CEM-I-25",
            description="Portland cement",
            quantity="5",
            unit="BAG",
            unit_price="4",
            currency="EUR",
            line_number=2,
        ),
    ]
    report = reconcile(_commercial(lines))

    assert report.status is MatchStatus.MATCHED
    by_product = {finding.product_code: finding for finding in report.findings}
    assert by_product["CEM-II-25"].ordered_quantity == Decimal("10")
    assert by_product["CEM-I-25"].ordered_quantity == Decimal("5")


def test_missing_identifier_is_not_applied_to_a_coded_product() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="CEM-II-25",
            description="Portland Cement CEM II 25kg",
            quantity="100",
            unit="BAG",
            unit_price="4.50",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="CEM-II-25",
            description="Portland Cement CEM II 25kg",
            quantity="100",
            unit="BAG",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code=None,
            description="CEM II/A-LL 25KG",
            quantity="100",
            unit="BAG",
            unit_price="4.50",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines))

    assert report.status is MatchStatus.NEEDS_REVIEW
    coded = [finding for finding in report.findings if finding.product_code == "CEM-II-25"]
    assert {finding.code for finding in coded} == {
        FindingCode.ORDERED_NOT_INVOICED,
        FindingCode.DELIVERED_NOT_INVOICED,
    }
    assert all(finding.invoiced_quantity == Decimal("0") for finding in coded)
    uncertain = next(
        finding
        for finding in report.findings
        if finding.code is FindingCode.UNCERTAIN_PRODUCT_MAPPING
    )
    assert uncertain.status is MatchStatus.NEEDS_REVIEW
    assert "CEM II/A-LL 25KG" in uncertain.message


def test_blank_product_code_is_not_an_identifier() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="  ",
            description="Same words",
            quantity="1",
            unit="EACH",
            unit_price="1",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code=None,
            description="Same words",
            quantity="1",
            unit="EACH",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="",
            description="Same words",
            quantity="1",
            unit="EACH",
            unit_price="1",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines))

    assert report.status is MatchStatus.NEEDS_REVIEW
    assert _codes(report) == {FindingCode.UNCERTAIN_PRODUCT_MAPPING}


def test_incompatible_units_are_not_subtracted() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="100",
            unit="BAG",
            unit_price="4",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="2500",
            unit="KG",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="100",
            unit="BAG",
            unit_price="4",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines))

    assert report.status is MatchStatus.NEEDS_REVIEW
    assert _codes(report) == {FindingCode.UNIT_MISMATCH}
    finding = report.findings[0]
    assert finding.quantity_difference is None
    assert finding.price_difference is None
    assert finding.ordered_quantity == Decimal("100")
    assert finding.delivered_quantity == Decimal("2500")


def test_unit_comparison_ignores_letter_case() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="2",
            unit="BAG",
            unit_price="4",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="2",
            unit="bag",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="CEM-II-25",
            description="Cement",
            quantity="2",
            unit="Bag",
            unit_price="4",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines))

    assert report.status is MatchStatus.MATCHED


def test_incompatible_currencies_are_not_converted() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="40",
            unit="EACH",
            unit_price="10",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="40",
            unit="EACH",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="40",
            unit="EACH",
            unit_price="10",
            currency="USD",
        ),
    ]
    report = reconcile(_commercial(lines, invoice_currency="USD"))

    assert report.status is MatchStatus.EXCEPTION
    assert FindingCode.PRICE_MISMATCH not in _codes(report)
    finding = next(item for item in report.findings if item.code is FindingCode.CURRENCY_MISMATCH)
    assert finding.price_difference is None
    assert finding.quantity_difference == Decimal("0")
    assert "EUR" in finding.message
    assert "USD" in finding.message


def test_missing_purchase_order_reference_is_reported_without_blocking_quantity_match() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="10",
            unit="TONNE",
            unit_price="20",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="10",
            unit="TONNE",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="10",
            unit="TONNE",
            unit_price="20",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines, delivery_references={"DN-1": None}))

    assert report.status is MatchStatus.EXCEPTION
    assert FindingCode.LINE_RECONCILED in _codes(report)
    assert FindingCode.MISSING_REFERENCE in _codes(report)


def test_decimal_tenths_sum_exactly() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="0.30",
            unit="TONNE",
            unit_price="10.10",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="0.10",
            unit="TONNE",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-2",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="0.20",
            unit="TONNE",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="AGG-20MM",
            description="Aggregate",
            quantity="0.30",
            unit="TONNE",
            unit_price="10.10",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines, delivery_numbers=("DN-1", "DN-2")))

    assert report.status is MatchStatus.MATCHED
    assert report.findings[0].delivered_quantity == Decimal("0.30")


def test_small_price_gap_is_not_rounded_away() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
            unit_price="1.004",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
            unit_price="1.005",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines))

    finding = report.findings[0]
    assert finding.code is FindingCode.PRICE_MISMATCH
    assert finding.price_difference == Decimal("0.001")
    assert isinstance(finding.price_difference, Decimal)


def test_zero_tolerance_does_not_hide_a_quantity_gap() -> None:
    report = reconcile(scenario_input(SCENARIO_B), MatchConfig())

    assert any(finding.quantity_difference == Decimal("20") for finding in report.findings)


def test_configured_tolerance_can_accept_a_smaller_gap() -> None:
    lines = [
        _line(
            DocumentType.PURCHASE_ORDER,
            "PO-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
            unit_price="1.000",
            currency="EUR",
        ),
        _line(
            DocumentType.DELIVERY_NOTE,
            "DN-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
        ),
        _line(
            DocumentType.INVOICE,
            "INV-1",
            product_code="TIM-C24-48",
            description="Timber",
            quantity="1",
            unit="EACH",
            unit_price="1.005",
            currency="EUR",
        ),
    ]
    report = reconcile(_commercial(lines), MatchConfig(price_tolerance=Decimal("0.01")))

    assert report.status is MatchStatus.MATCHED
    assert report.findings[0].purchase_order_unit_price == Decimal("1.000")
    assert report.findings[0].invoice_unit_price == Decimal("1.005")


def test_repeated_runs_return_the_same_report() -> None:
    payload = scenario_input(SCENARIO_B)
    first = reconcile(payload)
    second = reconcile(payload)

    assert first.model_dump() == second.model_dump()
    assert fingerprint_input(payload) == fingerprint_input(payload)


def test_float_quantities_are_rejected() -> None:
    with pytest.raises(ValueError, match="float"):
        SourceLine(
            document_type=DocumentType.PURCHASE_ORDER,
            document_number="PO-1",
            line_number=1,
            product_code="CEM-II-25",
            description="Cement",
            quantity=0.1,  # type: ignore[arg-type]
            unit="BAG",
            unit_price=Decimal("1"),
            currency="EUR",
        )


def test_negative_quantity_is_rejected() -> None:
    payload = _commercial(
        [
            _line(
                DocumentType.PURCHASE_ORDER,
                "PO-1",
                product_code="CEM-II-25",
                description="Cement",
                quantity="1",
                unit="BAG",
                unit_price="1",
                currency="EUR",
            ),
            _line(
                DocumentType.DELIVERY_NOTE,
                "DN-1",
                product_code="CEM-II-25",
                description="Cement",
                quantity="-1",
                unit="BAG",
            ),
            _line(
                DocumentType.INVOICE,
                "INV-1",
                product_code="CEM-II-25",
                description="Cement",
                quantity="1",
                unit="BAG",
                unit_price="1",
                currency="EUR",
            ),
        ]
    )
    with pytest.raises(ReconciliationInputError, match="positive"):
        reconcile(payload)


def test_matching_engine_does_not_import_io_or_persistence() -> None:
    tree = ast.parse(_ENGINE_PATH.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    forbidden = ("sqlalchemy", "fastapi", "httpx", "app.db", "app.api", "app.ai")
    assert all(not name.startswith(forbidden) for name in imported)
