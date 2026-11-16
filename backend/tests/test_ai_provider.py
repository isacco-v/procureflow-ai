import importlib
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.factory import build_ai_provider
from app.ai.provider import ChatMessage, CompletionRequest, RealProviderDisabledError
from app.core.config import Settings, get_settings
from app.db.session import dispose_db
from app.main import create_app


def _request() -> CompletionRequest:
    return CompletionRequest(
        purpose="provider-contract",
        messages=[ChatMessage(role="user", content="ping")],
    )


def test_mock_provider_is_deterministic_and_reports_zero_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    get_settings.cache_clear()

    provider = build_ai_provider(get_settings())
    first = provider.complete(_request())
    second = provider.complete(_request())

    assert provider.name == "mock"
    assert first == second
    assert first.provider == "mock"
    assert first.model == "mock"
    assert first.input_tokens == 0
    assert first.output_tokens == 0
    assert first.estimated_cost_usd == Decimal("0")
    assert "No model was called" in first.content
    get_settings.cache_clear()


def test_openai_mode_is_rejected_before_a_client_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    get_settings.cache_clear()

    with pytest.raises(RealProviderDisabledError):
        build_ai_provider(get_settings())

    get_settings.cache_clear()


def test_openai_sdk_is_not_installed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("openai")


def test_invalid_ai_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MODE", "vendor")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()


def test_defaults_use_mock_mode_without_an_env_file() -> None:
    settings = Settings(_env_file=None)

    assert settings.ai_mode == "mock"
    assert settings.openai_api_key is None


def test_health_can_report_openai_mode_without_invoking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MODE", "openai")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    dispose_db()

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ai_mode"] == "openai"
    dispose_db()
    get_settings.cache_clear()
