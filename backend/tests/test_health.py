from app.core.config import Settings


def test_health_returns_the_process_contract(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ProcureFlow AI",
        "environment": "test",
        "ai_mode": "mock",
    }
    assert response.headers["x-request-id"]


def test_health_echoes_a_safe_request_id(client) -> None:
    response = client.get("/health", headers={"x-request-id": "case-123"})

    assert response.headers["x-request-id"] == "case-123"


def test_health_replaces_an_unsafe_request_id(client) -> None:
    response = client.get("/health", headers={"x-request-id": "bad\nid"})

    returned = response.headers["x-request-id"]
    assert returned != "bad\nid"
    assert "\n" not in returned


def test_default_cors_allows_vite_on_either_loopback() -> None:
    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_allows_the_configured_frontend_origin(client) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_health_does_not_require_a_database(client) -> None:
    """The endpoint is liveness only, so Postgres does not need to be running."""

    response = client.get("/health")

    assert response.status_code == 200


def test_logs_redact_api_keys() -> None:
    import logging

    from app.core.logging import JsonFormatter

    record = logging.LogRecord(
        name="procureflow",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed for sk-test-secret-value",
        args=(),
        exc_info=None,
    )
    formatted = JsonFormatter().format(record)

    assert "sk-test-secret-value" not in formatted
    assert "[redacted]" in formatted
