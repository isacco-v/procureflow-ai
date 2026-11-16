from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness payload. It does not check the database or a model provider."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    environment: str
    ai_mode: Literal["mock", "openai"]
