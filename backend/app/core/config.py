from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Process configuration loaded from the environment and the root `.env` file.

    The OpenAI key is optional and is never required to start the API.
    `AI_MODE=openai` is recognized so misconfiguration is explicit, but the
    provider factory rejects it until a real client is intentionally added.
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
    openai_model: str = "gpt-4.1-mini"

    @field_validator("ai_mode", mode="before")
    @classmethod
    def normalize_ai_mode(cls, value: object) -> object:
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

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def blank_api_key_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
