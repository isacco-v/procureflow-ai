"""API tests against PostgreSQL.

The suite creates ``procureflow_test`` when the local server from Docker Compose
is reachable, migrates it, and skips when it is not.
"""

import os
import tempfile
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ProcurementCase,
    ProcurementDocument,
    PurchaseOrder,
    PurchaseOrderLine,
    ReconciliationRun,
    Supplier,
)
from app.db.session import dispose_db, get_engine
from app.main import create_app
from app.services.identifiers import synthetic_id

_ADMIN_DATABASE = "procureflow"
_TEST_DATABASE = "procureflow_test"
_DEFAULT_URL = "postgresql+psycopg://procureflow:procureflow@127.0.0.1:5432/procureflow"
_TRUNCATE = """
TRUNCATE TABLE
    extraction_validations,
    document_extractions,
    document_pages,
    investigation_citations,
    investigation_evidence,
    investigation_events,
    investigations,
    policy_sections,
    policy_documents,
    reconciliation_findings,
    reconciliation_runs,
    invoice_lines,
    invoices,
    delivery_note_lines,
    delivery_notes,
    purchase_order_lines,
    purchase_orders,
    procurement_documents,
    uploaded_documents,
    procurement_cases,
    suppliers
RESTART IDENTITY CASCADE
"""


def _database_urls() -> tuple[str, str]:
    configured = os.environ.get("DATABASE_URL", _DEFAULT_URL)
    parsed = make_url(configured)
    return (
        parsed.set(database=_ADMIN_DATABASE).render_as_string(hide_password=False),
        parsed.set(database=_TEST_DATABASE).render_as_string(hide_password=False),
    )


def _postgres_or_skip(admin_url: str) -> None:
    engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": _TEST_DATABASE},
            ).scalar()
            if exists is None:
                connection.execute(text(f"CREATE DATABASE {_TEST_DATABASE}"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    finally:
        engine.dispose()


def _alembic(database_url: str) -> Config:
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    dispose_db()
    return Config("alembic.ini")


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    admin_url, test_url = _database_urls()
    _postgres_or_skip(admin_url)
    previous = os.environ.get("DATABASE_URL")
    command.upgrade(_alembic(test_url), "head")
    try:
        yield test_url
    finally:
        dispose_db()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture
def postgres_client(
    migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", migrated_database)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("INVESTIGATION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DOCUMENT_EXTRACTOR", "mock")
    monkeypatch.setenv("EXTRACTION_LIVE_ENABLED", "false")
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", tempfile.mkdtemp(prefix="procureflow-docs-"))
    get_settings.cache_clear()
    dispose_db()
    _truncate()
    with TestClient(create_app()) as client:
        yield client
    _truncate()
    dispose_db()
    get_settings.cache_clear()


def _truncate() -> None:
    with get_engine().begin() as connection:
        connection.execute(text(_TRUNCATE))


def _run_count(case_id: str) -> int:
    with Session(get_engine()) as session:
        count = session.scalar(
            select(func.count())
            .select_from(ReconciliationRun)
            .where(ReconciliationRun.case_id == case_id)
        )
    return int(count or 0)


def test_domain_migration_round_trip_and_quantity_constraint(migrated_database: str) -> None:
    config = _alembic(migrated_database)
    command.downgrade(config, "20261116_0001")
    engine = create_engine(migrated_database)
    try:
        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert "procurement_cases" not in tables
        command.upgrade(config, "head")
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            tables = set(
                connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars()
            )
        assert version == "20261117_0006"
        assert "reconciliation_findings" in tables
        assert "investigations" in tables
        assert "uploaded_documents" in tables
        assert "policy_sections" in tables
        _reject_non_positive_quantity(engine)
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        dispose_db()


def _reject_non_positive_quantity(engine: Engine) -> None:
    supplier_id = synthetic_id("constraint-supplier")
    case_id = synthetic_id("constraint-case")
    document_id = synthetic_id("constraint-document")
    with Session(engine) as session:
        session.add_all(
            [
                Supplier(
                    id=supplier_id, code="SUP-CONSTRAINT", name="Constraint Check", synthetic=True
                ),
                ProcurementCase(
                    id=case_id,
                    reference="CASE-CONSTRAINT",
                    title="Constraint",
                    summary="Synthetic constraint check.",
                    synthetic=True,
                    supplier_id=supplier_id,
                ),
                ProcurementDocument(
                    id=document_id,
                    case_id=case_id,
                    document_type="purchase_order",
                    document_number="PO-CONSTRAINT",
                    synthetic=True,
                ),
                PurchaseOrder(
                    id=synthetic_id("constraint-purchase-order"),
                    case_id=case_id,
                    supplier_id=supplier_id,
                    source_document_id=document_id,
                    number="PO-CONSTRAINT",
                    currency="EUR",
                    issued_on=date(2026, 1, 1),
                ),
                PurchaseOrderLine(
                    id=synthetic_id("constraint-line"),
                    purchase_order_id=synthetic_id("constraint-purchase-order"),
                    source_document_id=document_id,
                    line_number=1,
                    product_code="CEM-II-25",
                    description="Cement",
                    quantity=Decimal("0"),
                    unit="BAG",
                    unit_price=Decimal("1"),
                    currency="EUR",
                ),
            ]
        )
        with pytest.raises(IntegrityError) as caught:
            session.commit()
    assert "ck_purchase_order_lines_quantity" in str(caught.value)


def test_seed_is_idempotent_and_labeled_synthetic(postgres_client: TestClient) -> None:
    first = postgres_client.post("/api/v1/dev/seed")
    second = postgres_client.post("/api/v1/dev/seed")

    assert first.status_code == 200
    assert first.json()["synthetic"] is True
    assert first.json()["cases_created"] == [
        "CASE-A-CLEAN",
        "CASE-B-QUANTITY",
        "CASE-C-AMBIGUOUS",
        "CASE-D-PARTIAL",
        "CASE-E-PRICE",
    ]
    assert second.status_code == 200
    assert second.json()["cases_created"] == []
    assert second.json()["cases_existing"] == first.json()["cases_created"]

    listed = postgres_client.get("/api/v1/cases")
    assert listed.status_code == 200
    cases = listed.json()["cases"]
    assert [case["reference"] for case in cases] == first.json()["cases_created"]
    assert all(case["synthetic"] is True for case in cases)
    assert all(case["supplier"]["synthetic"] is True for case in cases)
    assert all(case["latest_reconciliation_status"] is None for case in cases)


def test_unknown_case_is_a_not_found_error(postgres_client: TestClient) -> None:
    response = postgres_client.get("/api/v1/cases/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {
        "code": "case_not_found",
        "detail": "Procurement case was not found.",
    }


def test_seed_is_unavailable_when_the_environment_is_not_local(
    migrated_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_database)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    dispose_db()
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/dev/seed")
    dispose_db()
    get_settings.cache_clear()

    assert response.status_code == 404
    assert response.json()["code"] == "seed_unavailable"


def test_quantity_scenario_is_deterministic_and_idempotent(postgres_client: TestClient) -> None:
    postgres_client.post("/api/v1/dev/seed")
    case_id = str(synthetic_id("case:CASE-B-QUANTITY"))
    missing = postgres_client.get(f"/api/v1/cases/{case_id}/reconciliation")
    assert missing.status_code == 404
    assert missing.json()["code"] == "reconciliation_not_found"

    created = postgres_client.post(f"/api/v1/cases/{case_id}/reconciliation")
    replayed = postgres_client.post(f"/api/v1/cases/{case_id}/reconciliation")

    assert created.status_code == 201
    assert replayed.status_code == 200
    body = created.json()
    assert body["status"] == "EXCEPTION"
    assert body["replayed"] is False
    assert replayed.json()["id"] == body["id"]
    assert replayed.json()["replayed"] is True
    assert replayed.json()["input_fingerprint"] == body["input_fingerprint"]
    assert _run_count(case_id) == 1

    finding = next(item for item in body["findings"] if item["code"] == "INVOICED_WITHOUT_DELIVERY")
    assert finding["status"] == "EXCEPTION"
    assert finding["ordered_quantity"] == "100"
    assert finding["delivered_quantity"] == "80"
    assert finding["invoiced_quantity"] == "100"
    assert finding["quantity_difference"] == "20"
    assert finding["price_difference"] == "0"
    assert isinstance(finding["quantity_difference"], str)
    assert {reference["document_number"] for reference in finding["source_references"]} == {
        "PO-B-100",
        "DN-B-100",
        "INV-B-100",
    }
    assert all(reference["document_id"] for reference in finding["source_references"])

    stored = postgres_client.get(f"/api/v1/cases/{case_id}/reconciliation")
    assert stored.status_code == 200
    assert stored.json()["id"] == body["id"]
    by_id = postgres_client.get(f"/api/v1/cases/{case_id}/reconciliation/{body['id']}")
    assert by_id.status_code == 200
    assert by_id.json()["findings"] == body["findings"]


def test_remaining_scenarios_keep_their_contract(postgres_client: TestClient) -> None:
    postgres_client.post("/api/v1/dev/seed")
    expectations = {
        "CASE-A-CLEAN": ("MATCHED", {"LINE_RECONCILED"}),
        "CASE-C-AMBIGUOUS": ("NEEDS_REVIEW", {"UNCERTAIN_PRODUCT_MAPPING"}),
        "CASE-D-PARTIAL": ("MATCHED", {"LINE_RECONCILED"}),
        "CASE-E-PRICE": ("EXCEPTION", {"PRICE_MISMATCH"}),
    }
    for reference, (status, codes) in expectations.items():
        case_id = synthetic_id(f"case:{reference}")
        detail = postgres_client.get(f"/api/v1/cases/{case_id}")
        assert detail.status_code == 200
        assert detail.json()["synthetic"] is True
        response = postgres_client.post(f"/api/v1/cases/{case_id}/reconciliation")
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == status
        assert {finding["code"] for finding in body["findings"]} == codes

    partial = postgres_client.post(
        f"/api/v1/cases/{synthetic_id('case:CASE-D-PARTIAL')}/reconciliation"
    ).json()
    assert partial["replayed"] is True
    assert partial["findings"][0]["delivered_quantity"] == "100"
    price = postgres_client.get(
        f"/api/v1/cases/{synthetic_id('case:CASE-E-PRICE')}/reconciliation"
    ).json()
    assert price["findings"][0]["price_difference"] == "1.25"
    assert price["findings"][0]["purchase_order_unit_price"] == "12.5"
    assert price["findings"][0]["invoice_unit_price"] == "13.75"
