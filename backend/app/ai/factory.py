from app.ai.mock import MockAIProvider
from app.ai.provider import AIProvider, RealProviderDisabledError
from app.core.config import Settings


def build_ai_provider(settings: Settings) -> AIProvider:
    """Select the completion provider.

    This factory never constructs an OpenAI client. Live investigation calls
    use ``build_investigation_model`` and stay off unless the server-side live
    gate is open.
    """

    if settings.ai_mode == "mock":
        return MockAIProvider()

    raise RealProviderDisabledError(
        "The completion provider does not call OpenAI. No completion request is sent. "
        "Set AI_MODE=mock."
    )
