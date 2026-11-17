"""Extract page text with PyMuPDF.

The parser does not classify procurement fields and does not call OCR. PDF
metadata is returned for display. It is not a document identifier.
"""

import logging
from typing import Any

import pymupdf

from app.documents.models import ParsedDocument, ParsedPage, TextBlock

logger = logging.getLogger(__name__)

_IMAGE_ONLY_CHAR_THRESHOLD = 40
_METADATA_KEYS = ("title", "author", "creator", "producer", "subject")
_MAX_PAGE_CHARS = 20_000
_MAX_BLOCK_CHARS = 500
_MAX_BLOCKS = 80


class ParseError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def parse_pdf(data: bytes, *, max_pages: int) -> ParsedDocument:
    """Read page text, blocks, and basic metadata from PDF bytes."""

    if max_pages < 1:
        raise ParseError("too_many_pages", "The page limit must be at least 1.")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        logger.warning("pdf_open_failed", extra={"error_type": type(exc).__name__})
        raise ParseError("corrupt_pdf", "The PDF could not be read.") from None
    try:
        return _read_document(document, max_pages=max_pages)
    except ParseError:
        raise
    except Exception as exc:
        logger.warning("pdf_parse_failed", extra={"error_type": type(exc).__name__})
        raise ParseError("corrupt_pdf", "The PDF could not be read.") from None
    finally:
        document.close()


def _read_document(document: Any, *, max_pages: int) -> ParsedDocument:
    if document.is_encrypted and not document.authenticate(""):
        raise ParseError("encrypted_pdf", "Encrypted PDFs are not accepted.")
    page_count = document.page_count
    if page_count < 1:
        raise ParseError("corrupt_pdf", "The PDF could not be read.")
    if page_count > max_pages:
        raise ParseError(
            "too_many_pages",
            f"This PDF has {page_count} pages. The limit is {max_pages}.",
        )
    pages: list[ParsedPage] = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text")
        if not isinstance(text, str):
            text = ""
        text = text.replace("\x00", "")
        truncated = False
        if len(text) > _MAX_PAGE_CHARS:
            text = text[:_MAX_PAGE_CHARS]
            truncated = True
        blocks = _blocks(page)
        if truncated:
            text = f"{text}\n[page text truncated]"
        pages.append(ParsedPage(page_number=index, text=text, blocks=tuple(blocks)))
    char_count = sum(len("".join(page.text.split())) for page in pages)
    image_only = char_count < _IMAGE_ONLY_CHAR_THRESHOLD
    return ParsedDocument(
        page_count=page_count,
        pages=tuple(pages),
        metadata=_metadata(document),
        image_only=image_only,
        text_extractable=not image_only,
        char_count=char_count,
    )


def _blocks(page: Any) -> list[TextBlock]:
    raw_blocks = page.get_text("blocks")
    collected: list[TextBlock] = []
    if not isinstance(raw_blocks, list):
        return collected
    for block in raw_blocks:
        if not isinstance(block, tuple) or len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            bbox = (
                round(float(x0), 2),
                round(float(y0), 2),
                round(float(x1), 2),
                round(float(y1), 2),
            )
        except (TypeError, ValueError):
            continue
        collected.append(TextBlock(text=text.strip()[:_MAX_BLOCK_CHARS], bbox=bbox))
        if len(collected) >= _MAX_BLOCKS:
            break
    collected.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    return collected


def _metadata(document: Any) -> dict[str, str]:
    raw = document.metadata if isinstance(document.metadata, dict) else {}
    cleaned: dict[str, str] = {}
    for key in _METADATA_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            text = " ".join(value.split())
            if text:
                cleaned[key] = text[:200]
    return cleaned
