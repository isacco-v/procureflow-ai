"""Live-experiment preparation. These tests do not open a socket."""

import inspect

import pytest

from app.documents.evaluate import EvaluationReport, evaluate_mock_extraction, render_report
from app.documents.models import ExtractedDocument, ExtractedLine, SourceSnippet
from app.documents.parse import parse_pdf
from app.documents.synthetic import PDF_DIR, load_catalog
from app.experiments import build_procedure, render_procedure, verify_case_b_fixtures
from app.experiments.checks import assess_live_extraction, assess_live_quantity_investigation
from app.experiments.report import LiveExperimentReport, render_live_report


def test_case_b_fixtures_match_the_catalog() -> None:
    assert verify_case_b_fixtures() == []


def test_preparation_command_does_not_call_openai() -> None:
    source = inspect.getsource(build_procedure) + inspect.getsource(verify_case_b_fixtures)
    assert "OpenAI(" not in source
    assert "responses.create" not in source
    text = render_procedure(build_procedure(), [])
    assert "PF-LIVE-EXTRACT-PO-B" in text
    assert "PF-LIVE-INVESTIGATE-CASE-B" in text
    assert "PF-LIVE-INVESTIGATE-CASE-B-V2" in text
    assert "PF-LIVE-E2E-CASE-B" in text
    assert "No OpenAI request is sent" in text
    assert "estimated safeguards, not guaranteed provider billing caps" in text
    assert "gpt-5.4-mini" in text
    assert "0.05" in text
    assert "0.10" in text


def test_mock_evaluation_cannot_render_a_live_result() -> None:
    rendered = render_report(evaluate_mock_extraction())
    assert "not a language-model measurement" in rendered
    live = EvaluationReport(
        extractor="openai",
        mocked=False,
        language_model=True,
        disclaimer="live",
        dataset="procureflow-synthetic-documents",
        documents=(),
    )
    with pytest.raises(ValueError, match="cannot render a live"):
        render_report(live)


def test_live_report_rejects_a_mock_execution() -> None:
    report = LiveExperimentReport(
        test_id="PF-LIVE-EXTRACT-PO-B",
        model="gpt-5.4-mini",
        configuration="store=false",
        case_input="works_order-po-b-100.pdf",
        expected="PO-B-100",
        actual="PO-B-100",
        schema_validation="passed",
        evidence="page 1",
        tools="none",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd="0.000001",
        duration_seconds="1",
        errors="none",
        evaluation="pass",
        execution="mock",
    )
    with pytest.raises(ValueError, match="cannot record a mock"):
        render_live_report(report)


def test_live_report_contains_the_required_fields() -> None:
    rendered = render_live_report(
        LiveExperimentReport(
            test_id="PF-LIVE-INVESTIGATE-CASE-B",
            model="gpt-5.4-mini",
            configuration="max_retries=0, store=false",
            case_input="CASE-B-QUANTITY",
            expected="quantity review, no payment",
            actual="not run",
            schema_validation="not run",
            evidence="not run",
            tools="not run",
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd="not run",
            duration_seconds="not run",
            errors="not run",
            evaluation="not run",
        )
    )
    for label in (
        "Test identifier:",
        "Model and configuration:",
        "Input document or case:",
        "Expected result:",
        "Actual result:",
        "Schema validation:",
        "Retrieved evidence:",
        "Agent tools invoked:",
        "Tokens consumed:",
        "Estimated USD cost:",
        "Duration:",
        "Errors:",
        "Overall evaluation:",
        "not a mock-test result",
        "not a guaranteed billing cap",
    ):
        assert label in rendered


def test_live_extraction_check_uses_the_purchase_order_catalog() -> None:
    entry = next(
        item
        for item in load_catalog()["documents"]
        if item["file_name"] == "works_order-po-b-100.pdf"
    )
    parsed = parse_pdf((PDF_DIR / entry["file_name"]).read_bytes(), max_pages=5)
    page_text = {page.page_number: page.text for page in parsed.pages}
    assert "PO-B-100" in page_text[1]
    document = ExtractedDocument(
        document_type="purchase_order",
        document_number="PO-B-100",
        supplier_name="Helios Building Supplies",
        supplier_code="SUP-HELIOS",
        purchase_order_number="PO-B-100",
        document_date="2026-03-02",
        currency="EUR",
        lines=[
            ExtractedLine(
                line_number=1,
                product_code="CEM-II-25",
                description="Portland Cement CEM II 25kg",
                quantity="100",
                unit="BAG",
                unit_price="4.5",
                line_total="450",
            )
        ],
        net_amount="450",
        source_references=[
            SourceSnippet(field="document_number", page_number=1, snippet="PO-B-100")
        ],
    )
    mock_pass, mock_reasons = assess_live_extraction(
        document,
        entry,
        provider="mock",
        mocked=True,
        page_text=page_text,
    )
    assert mock_pass is False
    assert mock_reasons == ["This result is not a live extraction."]
    live_pass, live_reasons = assess_live_extraction(
        document,
        entry,
        provider="openai",
        mocked=False,
        page_text=page_text,
    )
    assert live_reasons == []
    assert live_pass is True
    drifted = document.model_copy(update={"lines": []})
    drifted_pass, drifted_reasons = assess_live_extraction(
        drifted,
        entry,
        provider="openai",
        mocked=False,
        page_text=page_text,
    )
    assert drifted_pass is False
    assert drifted_reasons


def test_live_investigation_check_rejects_a_mock_and_an_uncited_policy() -> None:
    mock_pass, mock_reasons = assess_live_quantity_investigation(
        {"provider": "mock", "reasoning_kind": "deterministic_test_double", "ai_mode": "mock"}
    )
    assert mock_pass is False
    assert mock_reasons == ["This result is not a live investigation."]
    live_pass, live_reasons = assess_live_quantity_investigation(
        {
            "provider": "openai",
            "reasoning_kind": "language_model",
            "ai_mode": "openai",
            "mock_execution": False,
            "review_required": True,
            "payment_authority": False,
            "status": "completed",
            "recommended_action": "request_quantity_credit",
            "summary": (
                "Ordered 100, delivered 80, invoiced 100. The remaining quantity may "
                "still be delivered. Request a credit only if the supplier confirms "
                "the balance will not be delivered. No invoice was approved and no "
                "payment was initiated."
            ),
            "input_tokens": 10,
            "output_tokens": 4,
            "estimated_cost_usd": "0.000010",
            "evidence_validated": True,
            "prerequisites": [{"kind": "future_delivery", "status": "unconfirmed"}],
            "citations": [{"section_code": "POL-QTY-001"}],
            "evidence": [
                {"label": "purchase_order_line:PO-B-100:1:CEM-II-25"},
                {"label": "delivery_note_line:DN-B-100:1:CEM-II-25"},
                {"label": "invoice_line:INV-B-100:1:CEM-II-25"},
            ],
            "events": [
                {
                    "tool_name": "get_reconciliation_findings",
                    "payload": {"evidence_labels": ["finding:quantity"]},
                },
                {
                    "tool_name": "get_purchase_order",
                    "payload": {"evidence_labels": ["purchase_order_line:PO-B-100:1:CEM-II-25"]},
                },
                {
                    "tool_name": "get_delivery_notes",
                    "payload": {"evidence_labels": ["delivery_note_line:DN-B-100:1:CEM-II-25"]},
                },
                {
                    "tool_name": "get_invoices",
                    "payload": {"evidence_labels": ["invoice_line:INV-B-100:1:CEM-II-25"]},
                },
                {
                    "tool_name": "search_procurement_policy",
                    "payload": {"policy_section_codes": ["POL-QTY-001"]},
                },
            ],
        }
    )
    assert live_reasons == []
    assert live_pass is True
    prose_only, prose_reasons = assess_live_quantity_investigation(
        {
            "provider": "openai",
            "reasoning_kind": "language_model",
            "ai_mode": "openai",
            "mock_execution": False,
            "review_required": True,
            "payment_authority": False,
            "status": "completed",
            "recommended_action": "request_quantity_credit",
            "summary": (
                "Ordered 100, delivered 80, invoiced 100. The remaining quantity may "
                "still be delivered. Request a credit only if the supplier confirms "
                "the balance will not be delivered."
            ),
            "prerequisites": [],
            "input_tokens": 10,
            "output_tokens": 4,
            "estimated_cost_usd": "0.000010",
            "evidence_validated": True,
            "citations": [{"section_code": "POL-QTY-001"}],
            "evidence": [
                {"label": "purchase_order_line:PO-B-100:1:CEM-II-25"},
                {"label": "delivery_note_line:DN-B-100:1:CEM-II-25"},
                {"label": "invoice_line:INV-B-100:1:CEM-II-25"},
            ],
            "events": [
                {
                    "tool_name": "search_procurement_policy",
                    "payload": {
                        "policy_section_codes": ["POL-QTY-001"],
                        "evidence_labels": [
                            "purchase_order_line:PO-B-100:1:CEM-II-25",
                            "delivery_note_line:DN-B-100:1:CEM-II-25",
                            "invoice_line:INV-B-100:1:CEM-II-25",
                        ],
                    },
                },
                {"tool_name": "get_purchase_order", "payload": {}},
                {"tool_name": "get_delivery_notes", "payload": {}},
                {"tool_name": "get_invoices", "payload": {}},
                {"tool_name": "get_reconciliation_findings", "payload": {}},
            ],
        }
    )
    assert prose_only is False
    assert any("prerequisite" in reason.lower() for reason in prose_reasons)
    cited, cited_reasons = assess_live_quantity_investigation(
        {
            "provider": "openai",
            "reasoning_kind": "language_model",
            "ai_mode": "openai",
            "mock_execution": False,
            "review_required": True,
            "payment_authority": False,
            "status": "completed",
            "recommended_action": "request_quantity_credit",
            "summary": "No invoice was approved and no payment was initiated.",
            "input_tokens": 10,
            "output_tokens": 4,
            "estimated_cost_usd": "0.000010",
            "citations": [{"section_code": "POL-NOT-RETRIEVED"}],
            "evidence": [{"label": "delivery_note:DN-B-100"}],
            "events": [
                {"tool_name": "get_reconciliation_findings", "payload": {}},
                {
                    "tool_name": "get_invoices",
                    "payload": {"evidence_labels": ["delivery_note:DN-B-100"]},
                },
                {
                    "tool_name": "search_procurement_policy",
                    "payload": {"policy_section_codes": ["POL-QTY-001"]},
                },
            ],
        }
    )
    assert cited is False
    assert any("citation" in reason.lower() for reason in cited_reasons)


def test_live_investigation_check_rejects_findings_without_source_lines() -> None:
    passed, reasons = assess_live_quantity_investigation(
        {
            "provider": "openai",
            "reasoning_kind": "language_model",
            "ai_mode": "openai",
            "mock_execution": False,
            "review_required": True,
            "payment_authority": False,
            "status": "completed",
            "evidence_validated": False,
            "recommended_action": "request_quantity_credit",
            "summary": (
                "100 bags ordered and invoiced versus 80 bags delivered. "
                "The supplier should be asked for a credit note."
            ),
            "input_tokens": 3699,
            "output_tokens": 414,
            "estimated_cost_usd": "0.004637",
            "citations": [{"section_code": "POL-QTY-001"}],
            "evidence": [{"label": "case:CASE-B-QUANTITY"}, {"label": "policy:POL-QTY-001"}],
            "events": [
                {
                    "tool_name": "get_reconciliation_findings",
                    "payload": {"evidence_labels": ["finding:INVOICED_WITHOUT_DELIVERY:CEM-II-25"]},
                },
                {
                    "tool_name": "get_procurement_case",
                    "payload": {"evidence_labels": ["case:CASE-B-QUANTITY"]},
                },
                {
                    "tool_name": "search_procurement_policy",
                    "payload": {
                        "policy_section_codes": ["POL-QTY-001"],
                        "evidence_labels": ["policy:POL-QTY-001"],
                    },
                },
            ],
        }
    )

    assert passed is False
    text = " ".join(reasons).lower()
    assert "primary evidence" in text
    assert "purchase-order line" in text
    assert "evidence-validated" in text or "http success" in text
