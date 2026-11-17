"""Score a mock extraction against the synthetic ground-truth catalog.

The report is a measurement of the deterministic test double. It is not a
language-model score, even when every field matches.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from app.documents.mock_extractor import MockDocumentExtractor
from app.documents.models import ExtractedDocument
from app.documents.parse import parse_pdf
from app.documents.synthetic import PDF_DIR, load_catalog

_DISCLAIMER = "Mock extraction evaluation. This is not a language-model measurement."
_DECIMAL_FIELDS = {
    "net_amount",
    "tax_rate_percent",
    "tax_amount",
    "amount_due",
    "quantity",
    "unit_price",
    "line_total",
}
_SCALAR_FIELDS = (
    "document_type",
    "document_number",
    "supplier_name",
    "supplier_code",
    "purchase_order_number",
    "document_date",
    "currency",
    "net_amount",
    "tax_rate_percent",
    "tax_amount",
    "amount_due",
)
_LINE_FIELDS = (
    "product_code",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "line_total",
)


@dataclass(frozen=True, slots=True)
class DocumentScore:
    file_name: str
    scenario_reference: str
    classification_correct: bool
    fields: int
    fields_correct: int
    missing_fields: int
    missing_fields_detected: int
    quantities: int
    quantities_correct: int
    prices: int
    prices_correct: int
    expected_lines: int
    matched_lines: int
    predicted_lines: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    extractor: str
    mocked: bool
    language_model: bool
    disclaimer: str
    dataset: str
    documents: tuple[DocumentScore, ...]

    @property
    def document_classification_accuracy(self) -> Decimal:
        return _ratio(
            sum(1 for item in self.documents if item.classification_correct),
            len(self.documents),
        )

    @property
    def exact_field_accuracy(self) -> Decimal:
        return _ratio(
            sum(item.fields_correct for item in self.documents),
            sum(item.fields for item in self.documents),
        )

    @property
    def missing_field_detection(self) -> Decimal:
        return _ratio(
            sum(item.missing_fields_detected for item in self.documents),
            sum(item.missing_fields for item in self.documents),
        )

    @property
    def quantity_accuracy(self) -> Decimal:
        return _ratio(
            sum(item.quantities_correct for item in self.documents),
            sum(item.quantities for item in self.documents),
        )

    @property
    def price_accuracy(self) -> Decimal:
        return _ratio(
            sum(item.prices_correct for item in self.documents),
            sum(item.prices for item in self.documents),
        )

    @property
    def line_item_coverage(self) -> Decimal:
        return _ratio(
            sum(item.matched_lines for item in self.documents),
            sum(item.expected_lines for item in self.documents),
        )

    @property
    def line_item_precision(self) -> Decimal:
        return _ratio(
            sum(item.matched_lines for item in self.documents),
            sum(item.predicted_lines for item in self.documents),
        )


def score_document(predicted: ExtractedDocument, expected: dict[str, object]) -> DocumentScore:
    """Compare one extraction with one ground-truth record.

    ``expected`` may contain catalog keys such as ``file_name``. Those keys
    are not read from the prediction and are not supplied to an extractor.
    """

    fields = 0
    correct = 0
    missing = 0
    detected = 0
    predicted_values = _scalar_values(predicted)
    for name in _SCALAR_FIELDS:
        fields += 1
        actual = predicted_values[name]
        truth = expected[name]
        if truth is None:
            missing += 1
            if actual is None:
                detected += 1
        if _equal(name, truth, actual):
            correct += 1

    expected_lines = expected["lines"]
    if not isinstance(expected_lines, list):
        raise TypeError("Ground truth lines must be a list.")
    predicted_by_number = {line.line_number: line for line in predicted.lines}
    matched = 0
    quantities = 0
    quantities_correct = 0
    prices = 0
    prices_correct = 0
    expected_numbers: set[int] = set()
    for raw_line in expected_lines:
        if not isinstance(raw_line, dict):
            raise TypeError("Ground truth line must be an object.")
        number = raw_line["line_number"]
        if not isinstance(number, int):
            raise TypeError("Ground truth line number must be an integer.")
        expected_numbers.add(number)
        predicted_line = predicted_by_number.get(number)
        line_matched = predicted_line is not None and _equal(
            "description",
            raw_line["description"],
            predicted_line.description,
        )
        if line_matched:
            matched += 1
        for name in _LINE_FIELDS:
            fields += 1
            actual = None if predicted_line is None else getattr(predicted_line, name)
            truth = raw_line[name]
            if truth is None:
                missing += 1
                if actual is None:
                    detected += 1
            if _equal(name, truth, actual):
                correct += 1
        quantities += 1
        if predicted_line is not None and _equal(
            "quantity", raw_line["quantity"], predicted_line.quantity
        ):
            quantities_correct += 1
        prices += 1
        actual_price = None if predicted_line is None else predicted_line.unit_price
        if _equal("unit_price", raw_line["unit_price"], actual_price):
            prices_correct += 1
    extra = [number for number in predicted_by_number if number not in expected_numbers]
    fields += len(extra)
    return DocumentScore(
        file_name=str(expected["file_name"]),
        scenario_reference=str(expected["scenario_reference"]),
        classification_correct=_equal(
            "document_type",
            expected["document_type"],
            predicted.document_type.value if predicted.document_type else None,
        ),
        fields=fields,
        fields_correct=correct,
        missing_fields=missing,
        missing_fields_detected=detected,
        quantities=quantities,
        quantities_correct=quantities_correct,
        prices=prices,
        prices_correct=prices_correct,
        expected_lines=len(expected_lines),
        matched_lines=matched,
        predicted_lines=len(predicted.lines),
    )


def evaluate_mock_extraction(*, max_pages: int = 20) -> EvaluationReport:
    """Parse the committed PDFs and score the mock extractor.

    The extractor receives parsed pages only. The catalog file name and hash
    are checked before that call and are not passed into it.
    """

    catalog = load_catalog()
    documents = catalog["documents"]
    if not isinstance(documents, list):
        raise TypeError("Ground truth documents must be a list.")
    scores: list[DocumentScore] = []
    extractor = MockDocumentExtractor()
    for entry in documents:
        if not isinstance(entry, dict):
            raise TypeError("Ground truth document must be an object.")
        file_name = entry["file_name"]
        if not isinstance(file_name, str):
            raise TypeError("Ground truth file name must be a string.")
        payload = (PDF_DIR / file_name).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry["content_sha256"]:
            raise ValueError(f"Fixture hash does not match the catalog for {file_name}.")
        parsed = parse_pdf(payload, max_pages=max_pages)
        predicted = extractor.extract(parsed).document
        scores.append(score_document(predicted, entry))
    dataset = catalog["dataset"]
    return EvaluationReport(
        extractor="mock",
        mocked=True,
        language_model=False,
        disclaimer=_DISCLAIMER,
        dataset=dataset if isinstance(dataset, str) else "procureflow-synthetic-documents",
        documents=tuple(scores),
    )


def render_report(report: EvaluationReport) -> str:
    if report.language_model or not report.mocked or report.extractor != "mock":
        raise ValueError("Mock evaluation cannot render a live language-model result.")
    lines = [
        report.disclaimer,
        f"Extractor: {report.extractor}",
        f"Mocked: {str(report.mocked).lower()}",
        f"Language model: {str(report.language_model).lower()}",
        f"Dataset: {report.dataset}",
        f"Documents: {len(report.documents)}",
        f"Document classification accuracy: {_percent(report.document_classification_accuracy)}",
        f"Exact field accuracy: {_percent(report.exact_field_accuracy)}",
        f"Missing-field detection: {_percent(report.missing_field_detection)}",
        f"Quantity accuracy: {_percent(report.quantity_accuracy)}",
        f"Price accuracy: {_percent(report.price_accuracy)}",
        f"Line-item coverage: {_percent(report.line_item_coverage)}",
        f"Line-item precision: {_percent(report.line_item_precision)}",
        "",
        "Per document:",
    ]
    for item in report.documents:
        lines.append(
            f"- {item.scenario_reference} {item.file_name}: "
            f"fields {item.fields_correct}/{item.fields}, "
            f"lines {item.matched_lines}/{item.expected_lines}"
        )
    return "\n".join(lines) + "\n"


def _scalar_values(document: ExtractedDocument) -> dict[str, object]:
    return {
        "document_type": None if document.document_type is None else document.document_type.value,
        "document_number": document.document_number,
        "supplier_name": document.supplier_name,
        "supplier_code": document.supplier_code,
        "purchase_order_number": document.purchase_order_number,
        "document_date": document.document_date,
        "currency": document.currency,
        "net_amount": document.net_amount,
        "tax_rate_percent": document.tax_rate_percent,
        "tax_amount": document.tax_amount,
        "amount_due": document.amount_due,
    }


def _equal(field: str, expected: object, actual: object) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if field in _DECIMAL_FIELDS:
        return Decimal(str(expected)) == Decimal(str(actual))
    return str(expected) == str(actual)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _percent(value: Decimal) -> str:
    return f"{value * 100:.2f}%"
