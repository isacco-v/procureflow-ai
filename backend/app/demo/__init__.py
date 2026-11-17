"""Mock end-to-end demonstration for Scenario B.

Uploads the three synthetic PDFs, accepts the mock extraction, reconciles, and
runs the scripted investigation. This module does not construct an OpenAI
client and does not send a model request. It is not a live experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.documents.synthetic import PDF_DIR

_FILES = (
    ("goods_received-dn-b-100.pdf", "delivery_note", "DN-B-100", "80"),
    ("works_order-po-b-100.pdf", "purchase_order", "PO-B-100", "100"),
    ("tax_invoice-inv-b-100.pdf", "invoice", "INV-B-100", "100"),
)
_DEMO_DATABASE = "procureflow_demo"


class DemoError(Exception):
    """The mock demonstration did not match the Scenario B contract."""


@dataclass(frozen=True, slots=True)
class MockDemoDocument:
    filename: str
    document_type: str
    document_number: str
    quantity: str


@dataclass(frozen=True, slots=True)
class MockDemoResult:
    case_id: str
    case_reference: str
    origin: str
    synthetic: bool
    reconciliation_status: str
    product_code: str
    unit: str
    ordered_quantity: str
    delivered_quantity: str
    invoiced_quantity: str
    quantity_difference: str
    finding_codes: tuple[str, ...]
    investigation_status: str
    recommended_action: str
    evidence_validated: bool
    mock_execution: bool
    model_name: str
    citations: tuple[str, ...]
    evidence_labels: tuple[str, ...]
    tool_names: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    payment_authority: bool
    review_required: bool
    summary: str
    documents: tuple[MockDemoDocument, ...]


def isolated_demo_url(configured: str) -> str:
    """Return a URL for ``procureflow_demo`` on the same server.

    The seeded database and the historical live rows stay on their own
    database. This function never returns that database name.
    """

    demo = make_url(configured).set(database=_DEMO_DATABASE)
    if demo.database != _DEMO_DATABASE:
        raise DemoError("The demonstration database name was not procureflow_demo.")
    rendered = demo.render_as_string(hide_password=False)
    if make_url(rendered).database != _DEMO_DATABASE:
        raise DemoError("The demonstration database name was not procureflow_demo.")
    return rendered


def run_case_b_mock_demo(client: TestClient) -> MockDemoResult:
    """Run Scenario B from the fixture PDFs through the mock investigation."""

    health = client.get("/health")
    _expect(health.status_code == 200, f"Health check failed: {health.text}")
    health_body = health.json()
    _expect(health_body.get("ai_mode") == "mock", "AI mode is not mock. No demonstration was run.")

    documents: list[MockDemoDocument] = []
    uploads: list[dict[str, object]] = []
    for filename, document_type, number, quantity in _FILES:
        uploaded = _upload(client, filename, document_type, number, quantity)
        uploads.append(uploaded)
        documents.append(
            MockDemoDocument(
                filename=filename,
                document_type=str(uploaded["document_type"]),
                document_number=str(uploaded["document_number"]),
                quantity=quantity,
            )
        )

    case_id = _accept_all(client, uploads)
    case = _get_json(client, f"/api/v1/cases/{case_id}")
    _expect(case["origin"] == "upload", "The case was not created from the upload.")
    _expect(case["synthetic"] is False, "The upload case was marked synthetic.")
    _expect(
        str(case["reference"]).startswith("UPL-"), "The case reference is not an upload reference."
    )
    _expect(case["reference"] != "CASE-B-QUANTITY", "The demonstration used the seeded case.")
    listed = _get_json(client, "/api/v1/cases")
    references = [item["reference"] for item in listed["cases"]]
    _expect(
        "CASE-B-QUANTITY" not in references,
        "The seeded quantity case is present. Use an empty demonstration database.",
    )

    reconciliation = _get_json(client, f"/api/v1/cases/{case_id}/reconciliation")
    _expect(reconciliation["status"] == "EXCEPTION", "Reconciliation did not report an exception.")
    gap = _finding(reconciliation, "INVOICED_WITHOUT_DELIVERY")
    ordered_gap = _finding(reconciliation, "ORDERED_NOT_DELIVERED")
    _expect(_decimal(gap["quantity_difference"]) == Decimal("20"), "The invoice gap is not 20.")
    _expect(
        _decimal(ordered_gap["quantity_difference"]) == Decimal("20"),
        "The delivery gap is not 20.",
    )
    _expect(_decimal(gap["ordered_quantity"]) == Decimal("100"), "Ordered quantity is not 100.")
    _expect(_decimal(gap["delivered_quantity"]) == Decimal("80"), "Delivered quantity is not 80.")
    _expect(_decimal(gap["invoiced_quantity"]) == Decimal("100"), "Invoiced quantity is not 100.")
    _expect(gap["product_code"] == "CEM-II-25", "The discrepancy is not for CEM-II-25.")
    _expect(gap["unit"] == "BAG", "The discrepancy unit is not BAG.")

    investigation = client.post(
        f"/api/v1/cases/{case_id}/reconciliation/{reconciliation['id']}/investigations"
    )
    _expect(
        investigation.status_code == 201,
        f"Investigation failed: {investigation.status_code} {investigation.text}",
    )
    body = investigation.json()
    _expect(body["mock_execution"] is True, "The investigation was not a mock execution.")
    _expect(body["ai_mode"] == "mock", "The investigation AI mode is not mock.")
    _expect(
        body["reasoning_kind"] == "deterministic_test_double",
        "The decision step was not the test double.",
    )
    _expect(body["status"] == "completed", "The mock investigation did not complete.")
    _expect(
        body["recommended_action"] == "request_supplier_clarification",
        "The mock recommendation was not supplier clarification.",
    )
    _expect(body["evidence_validated"] is True, "The evidence check did not accept the outcome.")
    _expect(body["review_required"] is True, "Human review was not required.")
    _expect(body["payment_authority"] is False, "The investigation was given payment authority.")
    _expect(
        body["input_tokens"] == 0 and body["output_tokens"] == 0, "The mock run recorded tokens."
    )
    _expect(_decimal(body["estimated_cost_usd"]) == Decimal("0"), "The mock run recorded a cost.")
    summary = str(body["summary"])
    _expect("no payment was initiated" in summary.lower(), "The summary does not refuse payment.")
    _expect("no invoice was approved" in summary.lower(), "The summary does not refuse approval.")
    citations = tuple(item["section_code"] for item in body["citations"])
    _expect("POL-QTY-001" in citations, "POL-QTY-001 was not cited.")
    labels = tuple(item["label"] for item in body["evidence"])
    for prefix in ("purchase_order_line:", "delivery_note_line:", "invoice_line:"):
        _expect(
            any(label.startswith(prefix) and "CEM-II-25" in label for label in labels),
            f"Retrieved evidence is missing {prefix}CEM-II-25.",
        )
    tool_names = tuple(
        event["tool_name"]
        for event in body["events"]
        if event["event_type"] == "tool_completed" and event["tool_name"]
    )
    for name in (
        "get_reconciliation_findings",
        "get_purchase_order",
        "get_delivery_notes",
        "get_invoices",
        "search_procurement_policy",
    ):
        _expect(name in tool_names, f"The tool trace is missing {name}.")

    return MockDemoResult(
        case_id=str(case["id"]),
        case_reference=str(case["reference"]),
        origin=str(case["origin"]),
        synthetic=False,
        reconciliation_status=str(reconciliation["status"]),
        product_code="CEM-II-25",
        unit="BAG",
        ordered_quantity=str(gap["ordered_quantity"]),
        delivered_quantity=str(gap["delivered_quantity"]),
        invoiced_quantity=str(gap["invoiced_quantity"]),
        quantity_difference=str(gap["quantity_difference"]),
        finding_codes=tuple(item["code"] for item in reconciliation["findings"]),
        investigation_status=str(body["status"]),
        recommended_action=str(body["recommended_action"]),
        evidence_validated=True,
        mock_execution=True,
        model_name=str(body["model_name"]),
        citations=citations,
        evidence_labels=labels,
        tool_names=tool_names,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=str(body["estimated_cost_usd"]),
        payment_authority=False,
        review_required=True,
        summary=summary,
        documents=tuple(documents),
    )


def render_mock_demo(result: MockDemoResult) -> str:
    """Format the demonstration. The wording says this is not a live result."""

    documents = "\n".join(
        (
            f"- {item.filename}: parsed as {item.document_type} {item.document_number}, "
            f"mock extraction quantity {item.quantity} BAG."
        )
        for item in result.documents
    )
    findings = ", ".join(result.finding_codes)
    citations = ", ".join(result.citations)
    tools = ", ".join(result.tool_names)
    return "\n".join(
        [
            "Mock end-to-end demonstration.",
            "This is not a live LLM experiment. No OpenAI request was sent.",
            "The decision step is a deterministic test double. Recorded usage is zero.",
            f"Case: {result.case_reference} ({result.case_id}).",
            f"Origin: {result.origin}. Synthetic: {str(result.synthetic).lower()}.",
            "Documents:",
            documents,
            (
                f"Reconciliation: {result.reconciliation_status}. "
                f"{result.product_code} ordered {result.ordered_quantity} {result.unit}, "
                f"delivered {result.delivered_quantity} {result.unit}, "
                f"invoiced {result.invoiced_quantity} {result.unit}, "
                f"gap {result.quantity_difference} {result.unit}."
            ),
            f"Finding codes: {findings}.",
            (
                f"Investigation: {result.investigation_status}, "
                f"action {result.recommended_action}, "
                f"evidence validated {str(result.evidence_validated).lower()}, "
                f"mock execution {str(result.mock_execution).lower()}, "
                f"test double {result.model_name}."
            ),
            f"Policy citations: {citations}.",
            f"Tool calls: {tools}.",
            (
                f"Tokens: input {result.input_tokens}, output {result.output_tokens}. "
                f"Estimated cost {result.estimated_cost_usd} USD."
            ),
            (
                f"Review required: {str(result.review_required).lower()}. "
                f"Payment authority: {str(result.payment_authority).lower()}."
            ),
            "The seeded CASE-B-QUANTITY rows were not used.",
            "",
        ]
    )


def _upload(
    client: TestClient,
    filename: str,
    document_type: str,
    number: str,
    quantity: str,
) -> dict[str, object]:
    payload = (PDF_DIR / filename).read_bytes()
    response = client.post(
        "/api/v1/documents",
        files={"file": (filename, payload, "application/pdf")},
    )
    _expect(
        response.status_code == 201,
        f"{filename} upload failed: {response.status_code} {response.text}",
    )
    body = response.json()
    page_text = "\n".join(page["text"] for page in body["pages"])
    _expect(
        f"Quantity: {quantity}" in page_text,
        f"{filename} page text does not contain Quantity: {quantity}.",
    )
    _expect(number in page_text, f"{filename} page text does not contain {number}.")
    _expect(body["mocked"] is True, f"{filename} was not extracted by the mock extractor.")
    _expect(body["extractor"] == "mock", f"{filename} extractor is not mock.")
    _expect(
        body["reasoning_kind"] == "deterministic_test_double",
        f"{filename} was not labeled as a deterministic test double.",
    )
    _expect(
        body["document_type"] == document_type,
        f"{filename} was classified as {body['document_type']}.",
    )
    _expect(body["document_number"] == number, f"{filename} number was {body['document_number']}.")
    _expect(body["ocr_applied"] is False, f"{filename} reported OCR.")
    line = body["extraction"]["lines"][0]
    _expect(
        _decimal(line["quantity"]) == Decimal(quantity),
        f"{filename} extracted quantity is {line['quantity']}.",
    )
    _expect(line["unit"] == "BAG", f"{filename} extracted unit is {line['unit']}.")
    _expect(
        line["product_code"] == "CEM-II-25",
        f"{filename} extracted product is {line['product_code']}.",
    )
    return body


def _accept_all(client: TestClient, uploads: list[dict[str, object]]) -> str:
    case_id: str | None = None
    for uploaded in uploads:
        response = client.post(f"/api/v1/documents/{uploaded['id']}/accept")
        number = uploaded["document_number"]
        detail = f"{response.status_code} {response.text}"
        _expect(response.status_code == 201, f"Accept failed for {number}: {detail}")
        body = response.json()
        _expect(body["origin"] == "upload", "Acceptance did not create an upload record.")
        _expect(body["synthetic"] is False, "Acceptance marked the case synthetic.")
        if case_id is None:
            case_id = str(body["case_id"])
        _expect(body["case_id"] == case_id, "The three documents were not accepted onto one case.")
    if case_id is None:
        raise DemoError("No document was accepted.")
    return case_id


def _get_json(client: TestClient, path: str) -> dict[str, object]:
    response = client.get(path)
    _expect(response.status_code == 200, f"{path} failed: {response.status_code} {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise DemoError(f"{path} did not return an object.")
    return body


def _finding(reconciliation: dict[str, object], code: str) -> dict[str, object]:
    findings = reconciliation["findings"]
    if not isinstance(findings, list):
        raise DemoError("Reconciliation findings were not a list.")
    for item in findings:
        if isinstance(item, dict) and item.get("code") == code:
            return item
    raise DemoError(f"Reconciliation is missing {code}.")


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise DemoError(message)
