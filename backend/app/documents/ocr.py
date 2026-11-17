"""Future OCR and vision fallback.

The class records that the capability is absent. ``parse_pdf`` does not call
it, and no vision model is invoked from this package.
"""

from typing import Protocol

from app.documents.models import ParsedDocument


class OcrNotImplementedError(NotImplementedError):
    """Raised if a caller asks the unimplemented fallback to read a page image."""


class OcrFallback(Protocol):
    implemented: bool

    def recognize_text(self, pdf_bytes: bytes) -> ParsedDocument:
        """Return page text recognized from a scan. Not available in this build."""


class UnavailableOcrFallback:
    """Placeholder for a later OCR or vision provider. It has no client and no model."""

    implemented = False

    def recognize_text(self, pdf_bytes: bytes) -> ParsedDocument:
        raise OcrNotImplementedError(
            "OCR and vision extraction are not implemented. Image-only pages stay unread."
        )


def recover_image_only(
    parsed: ParsedDocument,
    pdf_bytes: bytes,
    fallback: OcrFallback,
) -> ParsedDocument:
    """Leave image-only parses unchanged while OCR is unimplemented.

    ``pdf_bytes`` is accepted so a future implemented fallback can read the
    same file. This function does not call a model.
    """

    if not parsed.image_only or not fallback.implemented:
        return parsed
    return fallback.recognize_text(pdf_bytes)
