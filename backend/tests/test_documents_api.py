"""Document intake API tests against PostgreSQL."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PurchaseOrderLine
from app.db.session import get_engine
from app.documents.synthetic import render_pdf
from app.domain.scenarios import SCENARIOS
from app.services.identifiers import synthetic_id

pytest_plugins = ["tests.test_procurement_api"]


def _scenario(reference: str):
    return next(item for item in SCENARIOS if item.reference == reference)


def _upload(
    client: TestClient,
    reference: str,
    document_number: str,
    filename: str,
) -> dict[str, object]:
    scenario = _scenario(reference)
    document = next(item for item in scenario.documents if item.document_number == document_number)
    payload = render_pdf(document, scenario.supplier)
    response = client.post(
        "/api/v1/documents",
        files={"file": (filename, payload, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["content_source"] == "page_text"
    assert body["ocr_implemented"] is False
    assert body["ocr_applied"] is False
    assert body["mocked"] is True
    assert body["extractor"] == "mock"
    assert body["reasoning_kind"] == "deterministic_test_double"
    assert "language model" not in body["model_name"]
    return body


def test_upload_classifies_content_and_rejects_a_duplicate_write(
    postgres_client: TestClient,
) -> None:
    scenario = _scenario("CASE-B-QUANTITY")
    delivery = next(item for item in scenario.documents if item.document_number == "DN-B-100")
    payload = render_pdf(delivery, scenario.supplier)
    first = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("PO-B-100-invoice.pdf", payload, "application/pdf")},
    )
    assert first.status_code == 201, first.text
    uploaded = first.json()
    assert uploaded["document_type"] == "delivery_note"
    assert uploaded["document_number"] == "DN-B-100"
    assert uploaded["original_filename"] == "PO-B-100-invoice.pdf"
    assert uploaded["status"] == "needs_review"
    assert "parsed" in uploaded["stages"]
    assert uploaded["pdf_metadata"]["title"] == "Synthetic construction document"
    assert uploaded["mocked"] is True
    assert any(
        item["field"] == "document_number" and "DN-B-100" in item["snippet"]
        for item in uploaded["extraction"]["source_references"]
    )
    again = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("another-name.pdf", payload, "application/pdf")},
    )
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["id"] == uploaded["id"]
    listed = postgres_client.get("/api/v1/documents")
    assert listed.status_code == 200
    assert len(listed.json()["documents"]) == 1


def test_invalid_uploads_are_not_stored(postgres_client: TestClient) -> None:
    signature = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", b"hello", "application/pdf")},
    )
    assert signature.status_code == 422
    assert signature.json()["code"] == "invalid_pdf_signature"
    media = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", b"%PDF-1.7", "text/plain")},
    )
    assert media.status_code == 422
    assert media.json()["code"] == "unsupported_media_type"
    corrupt = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("broken.pdf", b"%PDF-1.4\nthis is not a pdf object", "application/pdf")},
    )
    assert corrupt.status_code == 422
    assert corrupt.json()["code"] == "corrupt_pdf"
    assert postgres_client.get("/api/v1/documents").json()["documents"] == []


def test_accept_quantity_case_reconciles_and_investigates(postgres_client: TestClient) -> None:
    uploads = [
        _upload(postgres_client, "CASE-B-QUANTITY", number, f"scan-{index}.pdf")
        for index, number in enumerate(("DN-B-100", "PO-B-100", "INV-B-100"))
    ]
    case_id = None
    for item in uploads:
        accepted = postgres_client.post(f"/api/v1/documents/{item['id']}/accept")
        assert accepted.status_code == 201, accepted.text
        body = accepted.json()
        assert body["synthetic"] is False
        assert body["origin"] == "upload"
        assert body["replayed"] is False
        case_id = body["case_id"]
    assert case_id is not None
    replayed = postgres_client.post(f"/api/v1/documents/{uploads[0]['id']}/accept")
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True
    detail = postgres_client.get(f"/api/v1/cases/{case_id}")
    assert detail.status_code == 200
    case = detail.json()
    assert case["synthetic"] is False
    assert case["origin"] == "upload"
    assert case["reference"].startswith("UPL-")
    assert all(document["origin"] == "upload" for document in case["documents"])
    assert all(document["upload_id"] is not None for document in case["documents"])
    assert case["purchase_order"]["lines"][0]["quantity"] == "100"
    assert case["delivery_notes"][0]["lines"][0]["quantity"] == "80"
    reconciliation = postgres_client.get(f"/api/v1/cases/{case_id}/reconciliation")
    assert reconciliation.status_code == 200
    assert reconciliation.json()["status"] == "EXCEPTION"
    gap = next(
        item
        for item in reconciliation.json()["findings"]
        if item["code"] == "INVOICED_WITHOUT_DELIVERY"
    )
    assert Decimal(gap["quantity_difference"]) == Decimal("20")
    investigation = postgres_client.post(
        f"/api/v1/cases/{case_id}/reconciliation/{reconciliation.json()['id']}/investigations"
    )
    assert investigation.status_code == 201, investigation.text
    assert investigation.json()["mock_execution"] is True
    assert investigation.json()["recommended_action"] == "request_supplier_clarification"
    assert investigation.json()["payment_authority"] is False
    assert investigation.json()["estimated_cost_usd"] == "0"


def test_two_delivery_notes_sum_after_acceptance(postgres_client: TestClient) -> None:
    numbers = ("DN-D-020", "DN-D-080", "INV-D-100", "PO-D-100")
    uploads = [
        _upload(postgres_client, "CASE-D-PARTIAL", number, f"delivery-{number}.bin.pdf")
        for number in numbers
    ]
    case_ids = set()
    for item in uploads:
        accepted = postgres_client.post(f"/api/v1/documents/{item['id']}/accept")
        assert accepted.status_code == 201, accepted.text
        case_ids.add(accepted.json()["case_id"])
    assert len(case_ids) == 1
    case_id = case_ids.pop()
    detail = postgres_client.get(f"/api/v1/cases/{case_id}").json()
    assert len(detail["delivery_notes"]) == 2
    assert sorted(note["number"] for note in detail["delivery_notes"]) == ["DN-D-020", "DN-D-080"]
    reconciliation = postgres_client.get(f"/api/v1/cases/{case_id}/reconciliation")
    assert reconciliation.json()["status"] == "MATCHED"


def test_acceptance_does_not_overwrite_seeded_records(postgres_client: TestClient) -> None:
    seeded = postgres_client.post("/api/v1/dev/seed")
    assert seeded.status_code == 200
    uploaded = _upload(postgres_client, "CASE-A-CLEAN", "PO-A-100", "unrelated.pdf")
    accepted = postgres_client.post(f"/api/v1/documents/{uploaded['id']}/accept")
    assert accepted.status_code == 409
    assert accepted.json()["code"] == "procurement_record_exists"
    case_id = synthetic_id("case:CASE-A-CLEAN")
    detail = postgres_client.get(f"/api/v1/cases/{case_id}")
    assert detail.json()["synthetic"] is True
    assert detail.json()["origin"] == "synthetic_seed"
    assert detail.json()["purchase_order"]["lines"][0]["quantity"] == "100"
    with Session(get_engine()) as session:
        quantity = session.scalar(
            select(PurchaseOrderLine.quantity).where(
                PurchaseOrderLine.id == synthetic_id("purchase-order-line:PO-A-100:1")
            )
        )
    assert quantity == Decimal("100")
    stored = postgres_client.get(f"/api/v1/documents/{uploaded['id']}")
    assert stored.json()["status"] == "needs_review"
    assert stored.json()["accepted_case_id"] is None


def test_ambiguous_upload_keeps_a_null_product_code(postgres_client: TestClient) -> None:
    uploaded = _upload(postgres_client, "CASE-C-AMBIGUOUS", "PO-C-100", "cement.pdf")
    assert uploaded["extraction"]["lines"][0]["product_code"] is None
    assert any(
        warning["code"] == "unresolved_product_identity"
        for warning in uploaded["validation"]["warnings"]
    )
    accepted = postgres_client.post(f"/api/v1/documents/{uploaded['id']}/accept")
    assert accepted.status_code == 201, accepted.text
    detail = postgres_client.get(f"/api/v1/cases/{accepted.json()['case_id']}").json()
    assert detail["origin"] == "upload"
    assert detail["purchase_order"]["lines"][0]["product_code"] is None
    reconciliation = postgres_client.get(
        f"/api/v1/cases/{accepted.json()['case_id']}/reconciliation"
    )
    assert reconciliation.json()["status"] == "NEEDS_REVIEW"


def test_mock_extraction_does_not_bypass_requested_live_extraction(
    postgres_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.ai.gating import live_extraction_allowed
    from app.core.config import get_settings
    from app.db.models import DocumentExtraction, PurchaseOrderLine
    from app.db.session import get_engine
    from app.documents.factory import build_document_extractor
    from app.documents.mock_extractor import MockDocumentExtractor
    from app.documents.models import ExtractionOutcome
    from app.services.identifiers import synthetic_id

    calls = {"count": 0}

    class FakeLiveExtractor:
        name = "openai"
        mocked = False
        model_name = "gpt-5.4-mini"
        reasoning_kind = "language_model"

        def extract(self, parsed: object) -> ExtractionOutcome:
            calls["count"] += 1
            mocked = MockDocumentExtractor().extract(parsed)  # type: ignore[arg-type]
            return ExtractionOutcome(
                document=mocked.document,
                provider="openai",
                mocked=False,
                model_name=self.model_name,
                reasoning_kind="language_model",
                input_tokens=20,
                output_tokens=10,
                estimated_cost_usd=Decimal("0.000100"),
                prompt_injection_flags=list(mocked.prompt_injection_flags),
            )

    def builder(settings: object) -> object:
        from app.core.config import Settings

        assert isinstance(settings, Settings)
        if settings.document_extractor == "openai" and live_extraction_allowed(settings):
            return FakeLiveExtractor()
        return build_document_extractor(settings)

    scenario = _scenario("CASE-B-QUANTITY")
    purchase_order = next(item for item in scenario.documents if item.document_number == "PO-B-100")
    payload = render_pdf(purchase_order, scenario.supplier)
    first = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("works-order.pdf", payload, "application/pdf")},
    )
    assert first.status_code == 201, first.text
    upload_id = first.json()["id"]
    assert first.json()["mocked"] is True

    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "openai")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    blocked = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("works-order.pdf", payload, "application/pdf")},
    )
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "live_extraction_disabled"
    assert calls["count"] == 0

    monkeypatch.setattr("app.services.documents.build_document_extractor", builder)
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "true")
    get_settings.cache_clear()
    live = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("works-order.pdf", payload, "application/pdf")},
    )
    assert live.status_code == 201, live.text
    assert live.json()["duplicate"] is False
    assert live.json()["id"] == upload_id
    assert live.json()["mocked"] is False
    assert live.json()["extractor"] == "openai"
    assert live.json()["document_number"] == "PO-B-100"
    assert calls["count"] == 1
    repeated = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("works-order.pdf", payload, "application/pdf")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["mocked"] is False
    assert calls["count"] == 1

    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "mock")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    mock_view = postgres_client.get(f"/api/v1/documents/{upload_id}")
    assert mock_view.status_code == 200
    assert mock_view.json()["mocked"] is True
    assert mock_view.json()["extractor"] == "mock"
    assert mock_view.json()["document_number"] == "PO-B-100"
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(DocumentExtraction)
            .where(DocumentExtraction.uploaded_document_id == UUID(upload_id))
        )
    assert count == 2

    seeded = postgres_client.post("/api/v1/dev/seed")
    assert seeded.status_code == 200, seeded.text
    seeded_case = postgres_client.get(f"/api/v1/cases/{synthetic_id('case:CASE-B-QUANTITY')}")
    assert seeded_case.json()["origin"] == "synthetic_seed"
    assert seeded_case.json()["purchase_order"]["lines"][0]["quantity"] == "100"
    blocked_accept = postgres_client.post(f"/api/v1/documents/{upload_id}/accept")
    assert blocked_accept.status_code == 409
    assert blocked_accept.json()["code"] == "procurement_record_exists"
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "openai")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    live_seed_accept = postgres_client.post(f"/api/v1/documents/{upload_id}/accept")
    assert live_seed_accept.status_code == 409
    assert live_seed_accept.json()["code"] == "procurement_record_exists"
    with Session(get_engine()) as session:
        seeded_quantity = session.scalar(
            select(PurchaseOrderLine.quantity).where(
                PurchaseOrderLine.id == synthetic_id("purchase-order-line:PO-B-100:1")
            )
        )
    assert seeded_quantity == Decimal("100")

    from dataclasses import replace

    isolated = replace(
        purchase_order,
        document_number="PO-ISO-900",
        purchase_order_number="PO-ISO-900",
    )
    isolated_payload = render_pdf(isolated, scenario.supplier)
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "mock")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    mock_isolated = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("isolated-order.pdf", isolated_payload, "application/pdf")},
    )
    assert mock_isolated.status_code == 201, mock_isolated.text
    isolated_id = mock_isolated.json()["id"]
    monkeypatch.setattr("app.services.documents.build_document_extractor", builder)
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "openai")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    live_isolated = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("isolated-order.pdf", isolated_payload, "application/pdf")},
    )
    assert live_isolated.status_code == 201, live_isolated.text
    assert live_isolated.json()["mocked"] is False
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "mock")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    accepted = postgres_client.post(f"/api/v1/documents/{isolated_id}/accept")
    assert accepted.status_code == 201, accepted.text
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "openai")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    live_accept = postgres_client.post(f"/api/v1/documents/{isolated_id}/accept")
    assert live_accept.status_code == 409
    assert live_accept.json()["code"] == "extraction_not_acceptable"
    detail = postgres_client.get(f"/api/v1/cases/{accepted.json()['case_id']}")
    assert detail.json()["origin"] == "upload"
    assert detail.json()["synthetic"] is False
    assert detail.json()["purchase_order"]["lines"][0]["quantity"] == "100"
    untouched = postgres_client.get(f"/api/v1/cases/{synthetic_id('case:CASE-B-QUANTITY')}")
    assert untouched.json()["origin"] == "synthetic_seed"
    assert untouched.json()["purchase_order"]["lines"][0]["quantity"] == "100"


def test_failed_live_extraction_is_not_retried_and_keeps_the_mock(
    postgres_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    from sqlalchemy.orm import Session

    from app.ai.gating import live_extraction_allowed
    from app.core.config import Settings, get_settings
    from app.db.models import DocumentExtraction
    from app.db.session import get_engine
    from app.documents.factory import build_document_extractor
    from app.documents.openai_extractor import DocumentExtractionError

    calls = {"count": 0}

    class FailingExtractor:
        name = "openai"
        mocked = False
        model_name = "gpt-5.4-mini"
        reasoning_kind = "language_model"

        def extract(self, parsed: object) -> object:
            calls["count"] += 1
            raise DocumentExtractionError(
                "extraction_timed_out",
                "The extraction request timed out. No fields were invented.",
                request_sent=True,
                input_tokens=4,
                output_tokens=0,
            )

    def builder(settings: object) -> object:
        assert isinstance(settings, Settings)
        if settings.document_extractor == "openai" and live_extraction_allowed(settings):
            return FailingExtractor()
        return build_document_extractor(settings)

    scenario = _scenario("CASE-B-QUANTITY")
    delivery = next(item for item in scenario.documents if item.document_number == "DN-B-100")
    payload = render_pdf(delivery, scenario.supplier)
    first = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("delivery.pdf", payload, "application/pdf")},
    )
    assert first.status_code == 201, first.text
    upload_id = first.json()["id"]
    monkeypatch.setattr("app.services.documents.build_document_extractor", builder)
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "openai")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()
    failed = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("delivery.pdf", payload, "application/pdf")},
    )
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["mocked"] is False
    assert failed.json()["error_code"] == "extraction_timed_out"
    assert calls["count"] == 1
    repeated = postgres_client.post(
        "/api/v1/documents",
        files={"file": ("delivery.pdf", payload, "application/pdf")},
    )
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert calls["count"] == 1
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "mock")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    mock_view = postgres_client.get(f"/api/v1/documents/{upload_id}")
    assert mock_view.json()["mocked"] is True
    assert mock_view.json()["status"] == "needs_review"
    assert mock_view.json()["document_number"] == "DN-B-100"
    with Session(get_engine()) as session:
        rows = list(
            session.scalars(
                select(DocumentExtraction).where(
                    DocumentExtraction.uploaded_document_id == UUID(upload_id)
                )
            )
        )
    assert {row.provider for row in rows} == {"mock", "openai"}
    assert next(row for row in rows if row.provider == "mock").error_code is None
