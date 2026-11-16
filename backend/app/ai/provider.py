from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class CompletionRequest(BaseModel):
    """A single model call with an explicit business purpose.

    `purpose` is required so later cost and audit records can say why the
    call existed. This bootstrap does not perform those calls.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessage] = Field(min_length=1)


class CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["mock", "openai"]
    model: str
    content: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)


class AIProvider(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...


class AIProviderError(Exception):
    """Base error for provider selection and execution."""


class RealProviderDisabledError(AIProviderError):
    """Raised when a paid provider is selected before it is implemented."""
