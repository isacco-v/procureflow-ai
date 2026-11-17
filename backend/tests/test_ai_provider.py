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


def test_openai_sdk_import_does_not_place_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed: list[dict[str, object]] = []

    class FailingClient:
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)
            raise AssertionError("OpenAI client constructed")

    import openai

    monkeypatch.setattr(openai, "OpenAI", FailingClient)
    importlib.import_module("openai")
    settings = Settings(_env_file=None)
    provider = build_ai_provider(settings)
    provider.complete(_request())

    from app.ai.investigation import build_investigation_model

    model = build_investigation_model(settings)
    assert provider.name == "mock"
    assert model.name == "mock"
    assert constructed == []


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
    assert settings.openai_model == "gpt-5.4-mini"
    assert settings.investigation_live_enabled is False
    assert settings.investigation_max_estimated_cost_usd == Decimal("0.10")
    assert settings.investigation_max_llm_requests == 6
    assert settings.investigation_max_iterations == 8
    assert settings.investigation_max_tool_calls == 12
    assert settings.openai_request_timeout_seconds == 30
    assert settings.investigation_timeout_seconds == 90
    assert settings.extraction_request_timeout_seconds == 20
    assert settings.openai_input_usd_per_million == Decimal("0.75")
    assert settings.openai_output_usd_per_million == Decimal("4.50")


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


def test_a_key_does_not_enable_a_live_investigation(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed: list[object] = []

    class FailingClient:
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)
            raise AssertionError("OpenAI client constructed")

    import openai

    from app.ai.investigation import build_investigation_model
    from app.ai.openai_investigation import OpenAIInvestigationModel

    monkeypatch.setattr(openai, "OpenAI", FailingClient)
    disabled = Settings(
        _env_file=None,
        ai_mode="openai",
        openai_api_key="sk-test-not-a-real-key",
        investigation_live_enabled=False,
    )
    missing_key = Settings(
        _env_file=None,
        ai_mode="openai",
        investigation_live_enabled=True,
    )
    mock_mode = Settings(
        _env_file=None,
        ai_mode="mock",
        openai_api_key="sk-test-not-a-real-key",
        investigation_live_enabled=True,
    )

    with pytest.raises(RealProviderDisabledError):
        build_investigation_model(disabled)
    with pytest.raises(RealProviderDisabledError):
        OpenAIInvestigationModel(disabled)
    with pytest.raises(RealProviderDisabledError):
        build_investigation_model(missing_key)
    assert build_investigation_model(mock_mode).name == "mock"
    assert constructed == []


def test_live_client_is_constructed_only_when_every_gate_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, object]] = []

    class RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            created.append(kwargs)

            def create(**_kwargs: object) -> None:
                raise AssertionError("OpenAI request")

            self.responses = type("Responses", (), {"create": staticmethod(create)})()

    import openai

    from app.ai.investigation import build_investigation_model

    monkeypatch.setattr(openai, "OpenAI", RecordingClient)
    settings = Settings(
        _env_file=None,
        ai_mode="openai",
        openai_api_key="sk-test-not-a-real-key",
        investigation_live_enabled=True,
    )

    model = build_investigation_model(settings)

    assert model.name == "openai"
    assert model.model_name == "gpt-5.4-mini"
    assert created[0]["api_key"] == "sk-test-not-a-real-key"
    assert created[0]["max_retries"] == 0
    assert created[0]["timeout"] == settings.openai_request_timeout_seconds
