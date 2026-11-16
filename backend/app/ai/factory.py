from app.ai.mock import MockAIProvider
from app.ai.provider import AIProvider, RealProviderDisabledError
from app.core.config import Settings


def build_ai_provider(settings: Settings) -> AIProvider:
    """Select the provider. The OpenAI branch refuses before any client exists."""

    if settings.ai_mode == "mock":
        return MockAIProvider()

    raise RealProviderDisabledError(
        "AI_MODE=openai is reserved for a later iteration. "
        "The OpenAI client is not installed and no request is sent. "
        "Set AI_MODE=mock."
    )
