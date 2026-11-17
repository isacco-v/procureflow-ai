from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Process configuration loaded from the environment and the root `.env` file.

    The OpenAI key is optional and is never required to start the API.
    A live investigation call needs ``AI_MODE=openai``,
    ``INVESTIGATION_LIVE_ENABLED=true``, and a non-empty server-side key.
    A live document extraction additionally needs ``DOCUMENT_EXTRACTOR=openai``
    and ``EXTRACTION_LIVE_ENABLED=true``. Those gates are independent.
    Any one of them missing keeps that path from constructing a client.
    The completion provider does not call OpenAI.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ProcureFlow AI"
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://procureflow:procureflow@127.0.0.1:5432/procureflow"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ai_mode: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-5.4-mini", min_length=1, max_length=64)
    # Price-table rates for gpt-5.4-mini. They estimate a request. They are not an invoice.
    openai_input_usd_per_million: Decimal = Field(default=Decimal("0.75"), ge=0)
    openai_output_usd_per_million: Decimal = Field(default=Decimal("4.50"), ge=0)
    openai_request_timeout_seconds: float = Field(default=10, ge=1, le=60)
    investigation_max_iterations: int = Field(default=8, ge=1, le=20)
    investigation_max_tool_calls: int = Field(default=12, ge=1, le=30)
    investigation_max_llm_requests: int = Field(default=6, ge=1, le=12)
    investigation_max_output_tokens: int = Field(default=1200, ge=16, le=8000)
    investigation_timeout_seconds: float = Field(default=15, ge=0, le=120)
    # Application budget for one investigation. An estimated safeguard, not a billing cap.
    investigation_max_estimated_cost_usd: Decimal = Field(default=Decimal("0.10"), ge=0)
    investigation_live_enabled: bool = False
    # Uploaded PDFs. The directory is outside the application package.
    document_storage_dir: str = ""
    document_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=52_428_800)
    document_max_pages: int = Field(default=20, ge=1, le=100)
    # mock: deterministic test double. openai: live extraction, still gated below.
    document_extractor: Literal["mock", "openai"] = "mock"
    extraction_live_enabled: bool = False
    extraction_max_output_tokens: int = Field(default=2000, ge=16, le=8000)
    # Separate from the investigation budget. An estimated safeguard, not a billing cap.
    extraction_max_estimated_cost_usd: Decimal = Field(default=Decimal("0.05"), ge=0)
    extraction_request_timeout_seconds: float = Field(default=20, ge=1, le=60)

    @field_validator("ai_mode", "document_extractor", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        if value not in _LOG_LEVELS:
            allowed = ", ".join(sorted(_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed}")
        return value

    @field_validator("openai_model", mode="before")
    @classmethod
    def strip_model_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def blank_api_key_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def document_storage_path(self) -> Path:
        configured = self.document_storage_dir.strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return _REPO_ROOT / "var" / "documents"


@lru_cache
def get_settings() -> Settings:
    return Settings()
