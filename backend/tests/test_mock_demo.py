"""Scenario B mock demonstration. These tests do not call OpenAI."""

import inspect
from decimal import Decimal

import pytest
from sqlalchemy.engine import make_url

from app.demo import isolated_demo_url, render_mock_demo, run_case_b_mock_demo

pytest_plugins = ["tests.test_procurement_api"]


def test_demo_url_never_points_at_the_seeded_database() -> None:
    configured = "postgresql+psycopg://procureflow:procureflow@127.0.0.1:5432/procureflow"
    demo = isolated_demo_url(configured)
    assert make_url(demo).database == "procureflow_demo"
    assert make_url(demo).database != make_url(configured).database


def test_demo_source_does_not_construct_an_openai_client() -> None:
    import app.demo as demo
    import app.demo.__main__ as entry

    source = inspect.getsource(demo) + inspect.getsource(entry)
    assert "OpenAI(" not in source
    assert "responses.create" not in source


def test_scenario_b_fixture_pdfs_end_to_end(
    postgres_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OpenAI client constructed")

    monkeypatch.setattr("openai.OpenAI", forbidden)
    result = run_case_b_mock_demo(postgres_client)
    rendered = render_mock_demo(result)

    assert "This is not a live LLM experiment." in rendered
    assert "No OpenAI request was sent." in rendered
    assert result.origin == "upload"
    assert result.synthetic is False
    assert result.case_reference.startswith("UPL-")
    assert result.reconciliation_status == "EXCEPTION"
    assert Decimal(result.ordered_quantity) == Decimal("100")
    assert Decimal(result.delivered_quantity) == Decimal("80")
    assert Decimal(result.invoiced_quantity) == Decimal("100")
    assert Decimal(result.quantity_difference) == Decimal("20")
    assert result.unit == "BAG"
    assert result.product_code == "CEM-II-25"
    assert "INVOICED_WITHOUT_DELIVERY" in result.finding_codes
    assert "ORDERED_NOT_DELIVERED" in result.finding_codes
    assert result.recommended_action == "request_supplier_clarification"
    assert result.evidence_validated is True
    assert result.mock_execution is True
    assert result.payment_authority is False
    assert result.review_required is True
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert Decimal(result.estimated_cost_usd) == Decimal("0")
    assert "POL-QTY-001" in result.citations
    assert "get_purchase_order" in result.tool_names
    assert "get_delivery_notes" in result.tool_names
    assert "get_invoices" in result.tool_names
    assert "search_procurement_policy" in result.tool_names
    assert any(
        label.startswith("purchase_order_line:") and "CEM-II-25" in label
        for label in result.evidence_labels
    )
    assert {item.document_number for item in result.documents} == {
        "DN-B-100",
        "PO-B-100",
        "INV-B-100",
    }
    assert "no payment was initiated" in result.summary.lower()
