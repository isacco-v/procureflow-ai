"""Map uploaded-document rows to API models."""

from pydantic import ValidationError

from app.db.models import DocumentExtraction, UploadedDocument
from app.documents.models import ExtractedDocument
from app.domain.matching.models import MatchStatus
from app.schemas.documents import (
    AcceptDocumentResponse,
    DocumentPageResponse,
    ExtractedDocumentResponse,
    ExtractionValidationResponse,
    TextBlockResponse,
    UploadDetailResponse,
    UploadSummaryResponse,
    ValidationWarningResponse,
)
from app.services.documents import AcceptedUpload, extraction_for_provider


def upload_summary(
    upload: UploadedDocument, *, duplicate: bool, provider: str
) -> UploadSummaryResponse:
    extraction = extraction_for_provider(upload, provider)
    extracted = _extracted(extraction)
    error_code, error_detail = _errors(upload, extraction)
    return UploadSummaryResponse(
        id=upload.id,
        original_filename=upload.original_filename,
        byte_size=upload.byte_size,
        sha256=upload.sha256,
        page_count=upload.page_count,
        status=_status(upload, extraction),  # type: ignore[arg-type]
        stages=list(upload.stages),
        error_code=error_code,
        error_detail=error_detail,
        image_only=upload.image_only,
        text_extractable=upload.text_extractable,
        ocr_applied=False,
        extractor=None if extraction is None else extraction.provider,  # type: ignore[arg-type]
        mocked=None if extraction is None else extraction.mocked,
        model_name=None if extraction is None else extraction.model_name,
        reasoning_kind=None if extraction is None else extraction.reasoning_kind,  # type: ignore[arg-type]
        document_type=None if extracted is None else extracted.document_type,
        document_number=None if extracted is None else extracted.document_number,
        accepted_case_id=upload.accepted_case_id
        if extraction is not None and upload.accepted_extraction_id == extraction.id
        else None,
        duplicate=duplicate,
        created_at=upload.created_at,
    )


def upload_detail(
    upload: UploadedDocument, *, duplicate: bool, provider: str
) -> UploadDetailResponse:
    summary = upload_summary(upload, duplicate=duplicate, provider=provider)
    extraction = extraction_for_provider(upload, provider)
    extracted = _extracted(extraction)
    validation = None if extraction is None else extraction.validation
    return UploadDetailResponse(
        **summary.model_dump(),
        media_type=upload.media_type,
        char_count=upload.char_count,
        pdf_metadata=dict(upload.pdf_metadata),
        pages=[
            DocumentPageResponse(
                page_number=page.page_number,
                text=page.text,
                blocks=[
                    TextBlockResponse.model_validate(block)
                    for block in page.blocks
                    if isinstance(block, dict)
                ],
            )
            for page in sorted(upload.pages, key=lambda item: item.page_number)
        ],
        extraction=None
        if extracted is None
        else ExtractedDocumentResponse.model_validate(extracted.model_dump()),
        validation=None
        if validation is None
        else ExtractionValidationResponse(
            status=validation.status,  # type: ignore[arg-type]
            blocking=validation.blocking,
            warnings=[
                ValidationWarningResponse.model_validate(item)
                for item in validation.warnings
                if isinstance(item, dict)
            ],
            normalized=validation.normalized if isinstance(validation.normalized, dict) else None,
            computed=validation.computed if isinstance(validation.computed, dict) else {},
        ),
        prompt_injection_flags=[]
        if extraction is None
        else list(extraction.prompt_injection_flags),
        input_tokens=None if extraction is None else extraction.input_tokens,
        output_tokens=None if extraction is None else extraction.output_tokens,
        estimated_cost_usd=None if extraction is None else extraction.estimated_cost_usd,
    )


def accept_response(result: AcceptedUpload) -> AcceptDocumentResponse:
    status = result.reconciliation_status
    return AcceptDocumentResponse(
        document_id=result.upload.id,
        case_id=result.case.id,
        case_reference=result.case.reference,
        procurement_document_id=result.procurement_document_id,
        replayed=result.replayed,
        reconciliation_id=result.reconciliation_id,
        reconciliation_status=None if status is None else MatchStatus(status),
        reconciliation_error=result.reconciliation_error,
    )


def _extracted(extraction: DocumentExtraction | None) -> ExtractedDocument | None:
    if extraction is None or extraction.error_code:
        return None
    try:
        return ExtractedDocument.model_validate(extraction.payload)
    except ValidationError:
        return None


def _status(upload: UploadedDocument, extraction: DocumentExtraction | None) -> str:
    if extraction is not None and upload.accepted_extraction_id == extraction.id:
        return "accepted"
    if extraction is not None and extraction.error_code:
        return "failed"
    if extraction is not None:
        return "needs_review"
    if upload.accepted_extraction_id is not None:
        return "needs_review"
    return upload.status


def _errors(
    upload: UploadedDocument, extraction: DocumentExtraction | None
) -> tuple[str | None, str | None]:
    if extraction is not None and extraction.error_code:
        return extraction.error_code, extraction.error_detail
    return upload.error_code, upload.error_detail
