"""Run the Scenario B mock demonstration on an isolated database.

Usage, from ``backend/``::

    uv run python -m app.demo

The command creates or reuses ``procureflow_demo``, migrates it, replaces only
that database's rows, and prints the mock result. It does not write to the
database named in ``DATABASE_URL`` and it does not call OpenAI.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import dispose_db
from app.demo import DemoError, isolated_demo_url, render_mock_demo, run_case_b_mock_demo
from app.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[3]
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
_SNAPSHOT = """
SELECT id::text, status, attempt::text,
       COALESCE(evidence_validated::text, ''),
       COALESCE(recommended_action, ''),
       input_tokens::text, output_tokens::text, estimated_cost_usd::text
FROM investigations
ORDER BY id
"""


def main() -> None:
    settings = get_settings()
    if (
        settings.ai_mode != "mock"
        or settings.document_extractor != "mock"
        or settings.investigation_live_enabled
        or settings.extraction_live_enabled
    ):
        print(
            "Refusing to run. AI_MODE and DOCUMENT_EXTRACTOR must be mock, "
            "and both live flags must be false. This command does not call OpenAI."
        )
        raise SystemExit(2)

    source_url = settings.database_url
    source_name = make_url(source_url).database
    demo_url = isolated_demo_url(source_url)
    if make_url(demo_url).database == source_name:
        print("Refusing to run. The demonstration database matches the configured database.")
        raise SystemExit(2)

    before = _snapshot(source_url)
    _ensure_database(source_url, "procureflow_demo")
    storage = _REPO_ROOT / "var" / "demo-documents"
    storage.mkdir(parents=True, exist_ok=True)
    _prepare_process(demo_url, storage)
    command.upgrade(_alembic(), "head")
    _truncate_demo()
    with TestClient(create_app()) as client:
        result = run_case_b_mock_demo(client)
    after = _snapshot(source_url)
    if before != after:
        print("The configured database changed. The demonstration is not successful.")
        raise SystemExit(1)
    print(render_mock_demo(result), end="")
    print(
        f"Isolated database: procureflow_demo. Configured database {source_name} was not modified."
    )
    print(
        "To browse the upload case, start the API with DATABASE_URL pointed at "
        "procureflow_demo and DOCUMENT_STORAGE_DIR=var/demo-documents. Leave AI_MODE=mock."
    )
    print("Historical live reports were not modified. This was not a live LLM run.")


def _prepare_process(demo_url: str, storage: Path) -> None:
    os.environ["DATABASE_URL"] = demo_url
    os.environ["AI_MODE"] = "mock"
    os.environ["DOCUMENT_EXTRACTOR"] = "mock"
    os.environ["INVESTIGATION_LIVE_ENABLED"] = "false"
    os.environ["EXTRACTION_LIVE_ENABLED"] = "false"
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["DOCUMENT_STORAGE_DIR"] = str(storage)
    os.environ["APP_ENV"] = "development"
    get_settings.cache_clear()
    dispose_db()


def _alembic() -> Config:
    get_settings.cache_clear()
    dispose_db()
    return Config("alembic.ini")


def _ensure_database(admin_url: str, name: str) -> None:
    if name != "procureflow_demo":
        raise DemoError("Refusing to create a database other than procureflow_demo.")
    engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if exists is None:
                connection.execute(text(f"CREATE DATABASE {name}"))
    except SQLAlchemyError as exc:
        raise SystemExit(f"PostgreSQL is not available: {exc.__class__.__name__}") from exc
    finally:
        engine.dispose()


def _truncate_demo() -> None:
    from app.db.session import get_engine

    database = make_url(get_settings().database_url).database
    if database != "procureflow_demo":
        raise DemoError("Refusing to reset a database other than procureflow_demo.")
    with get_engine().begin() as connection:
        connection.execute(text(_TRUNCATE))


def _snapshot(url: str) -> tuple[tuple[str, ...], ...]:
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            rows = connection.execute(text(_SNAPSHOT)).all()
    except SQLAlchemyError as exc:
        if "does not exist" in str(exc).lower():
            return ()
        raise SystemExit(
            f"Could not read the configured database: {exc.__class__.__name__}"
        ) from exc
    finally:
        engine.dispose()
    return tuple(tuple(str(value) for value in row) for row in rows)


if __name__ == "__main__":
    try:
        main()
    except DemoError as exc:
        print(f"Mock demonstration failed: {exc}")
        raise SystemExit(1) from exc
