"""Select the document extractor. The default is the mock test double."""

from typing import Protocol

from app.ai.provider import RealProviderDisabledError
from app.core.config import Settings
from app.documents.mock_extractor import MockDocumentExtractor
from app.documents.models import ExtractionOutcome, ParsedDocument
from app.documents.openai_extractor import OpenAIDocumentExtractor


class DocumentExtractor(Protocol):
    name: str
    mocked: bool
    model_name: str

    def extract(self, parsed: ParsedDocument) -> ExtractionOutcome: ...


def build_document_extractor(settings: Settings) -> DocumentExtractor:
    """Return the configured extractor.

    ``DOCUMENT_EXTRACTOR=mock`` never constructs an OpenAI client. The live
    extractor is returned only when its own gate is open, which is separate
    from the investigation gate.
    """

    if settings.document_extractor == "mock":
        return MockDocumentExtractor()
    if settings.document_extractor != "openai":
        raise RealProviderDisabledError(
            "The document extractor is not available. No request is sent."
        )
    return OpenAIDocumentExtractor(settings)
