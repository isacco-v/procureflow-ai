from alembic.config import Config
from alembic.script import ScriptDirectory

import app.db.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import dispose_db, get_engine


def test_metadata_registers_procurement_tables() -> None:
    assert {
        "delivery_note_lines",
        "delivery_notes",
        "invoice_lines",
        "invoices",
        "procurement_cases",
        "procurement_documents",
        "purchase_order_lines",
        "purchase_orders",
        "reconciliation_findings",
        "reconciliation_runs",
        "suppliers",
    } <= set(Base.metadata.tables)


def test_engine_uses_the_configured_database_without_connecting(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://procureflow:procureflow@db.example:5432/procureflow_test",
    )
    get_settings.cache_clear()
    dispose_db()

    engine = get_engine()

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "db.example"
    assert engine.url.database == "procureflow_test"
    dispose_db()
    get_settings.cache_clear()


def test_alembic_has_a_single_baseline_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20261116_0002"]
