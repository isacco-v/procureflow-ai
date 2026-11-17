from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import dispose_db
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("INVESTIGATION_LIVE_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://procureflow:procureflow@localhost:5432/procureflow",
    )
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    dispose_db()
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
    dispose_db()
    get_settings.cache_clear()
