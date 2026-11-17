"""Server-side gate for a paid investigation call.

The browser cannot satisfy this gate. A request body, a header, and the
presence of an API key are each insufficient on their own.
"""

from app.core.config import Settings


def live_investigation_allowed(settings: Settings) -> bool:
    """Return whether this process may construct a live investigation client."""

    key = settings.openai_api_key
    if settings.ai_mode != "openai" or not settings.investigation_live_enabled or key is None:
        return False
    return bool(key.get_secret_value().strip())


def live_extraction_allowed(settings: Settings) -> bool:
    """Return whether this process may construct a live document-extraction client.

    The extraction budget and this flag are separate from the investigation
    gate. A key, ``AI_MODE=openai``, or an enabled investigation is not enough.
    """

    key = settings.openai_api_key
    if (
        settings.ai_mode != "openai"
        or settings.document_extractor != "openai"
        or not settings.extraction_live_enabled
        or key is None
    ):
        return False
    return bool(key.get_secret_value().strip())
