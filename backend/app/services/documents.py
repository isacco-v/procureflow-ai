"""Accept, parse, extract, and explicitly commit an uploaded PDF.

The file name is stored for display. Classification uses page text. Nothing in
this module overwrites an existing purchase order, delivery note, or invoice.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.provider import RealProviderDisabledError
from app.core.config import Settings
from app.db.models import (
    DeliveryNote,
    DeliveryNoteLine,
    DocumentExtraction,
    DocumentPage,
    ExtractionValidation,
    Invoice,
    InvoiceLine,
    ProcurementCase,
    ProcurementDocument,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    UploadedDocument,
)
from app.documents.factory import build_document_extractor
from app.documents.models import NormalizedDocument, ParsedDocument, ParsedPage, TextBlock
from app.documents.openai_extractor import DocumentExtractionError
from app.documents.parse import ParseError, parse_pdf
from app.documents.validation import validate_extraction
from app.domain.matching.models import DocumentType
from app.services.errors import ConflictError, NotFoundError, ProcurementError, UnavailableError
from app.services.reconciliation import latest_reconciliation, run_reconciliation
from app.services.storage import LocalDocumentStore, storage_key

logger = logging.getLogger(__name__)

_MEDIA_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_FILENAME = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass(frozen=True, slots=True)
class StoredUpload:
    upload: UploadedDocument
    duplicate: bool


@dataclass(frozen=True, slots=True)
class AcceptedUpload:
    upload: UploadedDocument
    case: ProcurementCase
    procurement_document_id: UUID
    replayed: bool
    reconciliation_id: UUID | None
    reconciliation_status: str | None
    reconciliation_error: str | None


def display_filename(name: str | None) -> str:
    """Return a short display name. It is not used to classify the PDF."""

    raw = Path(name or "document.pdf").name
    cleaned = _FILENAME.sub("_", raw).strip(" .")
    return (cleaned or "document.pdf")[:200]


def media_type_base(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def assess_upload(data: bytes, media_type: str | None, *, max_bytes: int) -> None:
    """Reject an upload that fails type, signature, or size checks. The bytes are not stored."""

    if media_type_base(media_type) not in _MEDIA_TYPES:
        raise ProcurementError(
            "unsupported_media_type",
            "Upload a PDF with content type application/pdf.",
            422,
        )
    if len(data) == 0:
        raise ProcurementError("empty_file", "The file is empty.", 422)
    if len(data) > max_bytes:
        raise ProcurementError(
            "file_too_large",
            f"The file exceeds the {max_bytes} byte limit.",
            422,
        )
    if not data.startswith(b"%PDF-"):
        raise ProcurementError(
            "invalid_pdf_signature",
            "The file does not start with a PDF signature.",
            422,
        )


def read_limited(file_obj: object, max_bytes: int) -> bytes:
    read = getattr(file_obj, "read", None)
    if read is None:
        raise ProcurementError("empty_file", "The file is empty.", 422)
    blob = read(max_bytes + 1)
    if isinstance(blob, str):
        raise ProcurementError(
            "invalid_pdf_signature", "The file does not start with a PDF signature.", 422
        )
    if not isinstance(blob, bytes):
        raise ProcurementError("empty_file", "The file is empty.", 422)
    return blob


def _accepted_from_other_extractor(upload: UploadedDocument, provider: str) -> bool:
    if upload.accepted_extraction_id is None:
        return False
    for item in upload.extractions:
        if item.id == upload.accepted_extraction_id:
            return item.provider != provider
    return False


def requested_provider(settings: Settings) -> str:
    """Return the extractor the process is configured to use."""

    if settings.document_extractor == "openai":
        return "openai"
    return "mock"


def extraction_for_provider(upload: UploadedDocument, provider: str) -> DocumentExtraction | None:
    for item in upload.extractions:
        if item.provider == provider:
            return item
    return None


def list_uploads(session: Session) -> list[UploadedDocument]:
    rows = session.scalars(
        select(UploadedDocument)
        .options(selectinload(UploadedDocument.extractions))
        .order_by(UploadedDocument.created_at.desc(), UploadedDocument.id.desc())
        .limit(100)
    )
    return list(rows)


def get_upload(session: Session, upload_id: UUID) -> UploadedDocument:
    upload = session.scalar(
        select(UploadedDocument)
        .where(UploadedDocument.id == upload_id)
        .options(
            selectinload(UploadedDocument.pages),
            selectinload(UploadedDocument.extractions).selectinload(DocumentExtraction.validation),
        )
    )
    if upload is None:
        raise NotFoundError("document_not_found", "Uploaded document was not found.")
    return upload


def intake_pdf(
    session: Session,
    settings: Settings,
    *,
    data: bytes,
    filename: str | None,
    media_type: str | None,
) -> StoredUpload:
    assess_upload(data, media_type, max_bytes=settings.document_max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    existing = _by_hash(session, digest)
    if existing is not None:
        return _resume_existing(session, settings, existing)
    try:
        parsed = parse_pdf(data, max_pages=settings.document_max_pages)
    except ParseError as exc:
        raise ProcurementError(exc.code, exc.detail, 422) from exc
    extractor = None
    if not parsed.image_only:
        try:
            extractor = build_document_extractor(settings)
        except RealProviderDisabledError as exc:
            raise UnavailableError("live_extraction_disabled", str(exc)) from exc

    store = LocalDocumentStore(settings.document_storage_path)
    key = storage_key(digest)
    store.put_if_absent(key, data)
    now = datetime.now(UTC)
    upload = UploadedDocument(
        original_filename=display_filename(filename),
        media_type=media_type_base(media_type),
        byte_size=len(data),
        sha256=digest,
        storage_key=key,
        page_count=parsed.page_count,
        status="needs_review",
        stages=["received", "parsed"],
        text_extractable=parsed.text_extractable,
        image_only=parsed.image_only,
        ocr_applied=False,
        char_count=parsed.char_count,
        pdf_metadata=parsed.metadata,
        created_at=now,
        updated_at=now,
    )
    session.add(upload)
    session.flush()
    for page in parsed.pages:
        session.add(
            DocumentPage(
                uploaded_document_id=upload.id,
                page_number=page.page_number,
                text=page.text,
                blocks=[{"text": block.text, "bbox": list(block.bbox)} for block in page.blocks],
            )
        )
    if parsed.image_only:
        upload.status = "needs_review"
        upload.error_code = "image_only_pdf"
        upload.error_detail = (
            "This PDF has no extractable text. OCR and vision are not implemented, "
            "so the page image was not read."
        )
        upload.stages = ["received", "parsed", "needs_review"]
    elif extractor is not None:
        _extract(session, upload, extractor, parsed)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _by_hash(session, digest)
        if raced is not None:
            return StoredUpload(upload=raced, duplicate=True)
        raise
    stored = get_upload(session, upload.id)
    return StoredUpload(upload=stored, duplicate=False)


def accept_upload(session: Session, upload_id: UUID, settings: Settings) -> AcceptedUpload:
    upload = get_upload(session, upload_id)
    if upload.status == "accepted":
        if _accepted_from_other_extractor(upload, requested_provider(settings)):
            raise ConflictError(
                "extraction_not_acceptable",
                "This file was accepted from a different extractor. "
                "Stored procurement records were not changed.",
            )
        return _replay_acceptance(session, upload)
    extraction = extraction_for_provider(upload, requested_provider(settings))
    if upload.status != "needs_review" or extraction is None or extraction.error_code is not None:
        raise ConflictError(
            "document_not_acceptable",
            "This document cannot be accepted for the configured extractor. "
            "Stored procurement records were not changed.",
        )
    validation = extraction.validation
    if validation is None or validation.blocking or validation.normalized is None:
        raise ConflictError(
            "extraction_not_acceptable",
            "Blocking validation warnings must be reviewed before acceptance. "
            "Stored procurement records were not changed.",
        )
    normalized = NormalizedDocument.model_validate(validation.normalized)
    supplier = _supplier_for_acceptance(session, normalized)
    if _commercial_exists(
        session, supplier.id, normalized.document_type, normalized.document_number
    ):
        raise ConflictError(
            "procurement_record_exists",
            "A procurement record with this supplier and document number already exists. "
            "It was not changed.",
        )
    case = _upload_case(session, supplier.id, normalized.purchase_order_number)
    if (
        case is not None
        and normalized.document_type is DocumentType.PURCHASE_ORDER
        and _case_has_purchase_order(session, case.id)
    ):
        raise ConflictError(
            "procurement_record_exists",
            "This upload case already has a purchase order. It was not changed.",
        )
    if case is None:
        case = ProcurementCase(
            reference=_unique_reference(
                session,
                f"UPL-{normalized.purchase_order_number or normalized.document_number}",
            ),
            title=f"Uploaded {normalized.purchase_order_number or normalized.document_number}",
            summary=(
                "Created from an accepted PDF upload. These records are not the "
                "seeded demonstration cases."
            ),
            synthetic=False,
            origin="upload",
            supplier_id=supplier.id,
        )
        session.add(case)
        session.flush()
    source = ProcurementDocument(
        case_id=case.id,
        document_type=normalized.document_type.value,
        document_number=normalized.document_number,
        synthetic=False,
        origin="upload",
        upload_id=upload.id,
    )
    session.add(source)
    session.flush()
    _insert_commercial(session, case, supplier, source, normalized)
    upload.status = "accepted"
    upload.accepted_case_id = case.id
    upload.accepted_extraction_id = extraction.id
    upload.error_code = None
    upload.error_detail = None
    upload.stages = [*list(upload.stages), "accepted"]
    upload.updated_at = datetime.now(UTC)
    case.updated_at = upload.updated_at
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "procurement_record_exists",
            "A procurement record with this supplier and document number already exists. "
            "It was not changed.",
        ) from exc
    reconciliation_id, reconciliation_status, reconciliation_error = _reconcile(session, case.id)
    stored = get_upload(session, upload.id)
    return AcceptedUpload(
        upload=stored,
        case=case,
        procurement_document_id=source.id,
        replayed=False,
        reconciliation_id=reconciliation_id,
        reconciliation_status=reconciliation_status,
        reconciliation_error=reconciliation_error,
    )


def _resume_existing(
    session: Session, settings: Settings, upload: UploadedDocument
) -> StoredUpload:
    """Reuse stored bytes. Run the requested extractor only when its row is missing.

    A mock extraction is not returned as the result of a live request. A failed
    live extraction is returned as stored and is not sent again.
    """

    provider = requested_provider(settings)
    if extraction_for_provider(upload, provider) is not None or upload.image_only:
        return StoredUpload(upload=upload, duplicate=True)
    try:
        extractor = build_document_extractor(settings)
    except RealProviderDisabledError as exc:
        raise UnavailableError("live_extraction_disabled", str(exc)) from exc
    _extract(session, upload, extractor, _parsed_from_upload(upload))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _by_hash(session, upload.sha256)
        if raced is not None and extraction_for_provider(raced, provider) is not None:
            return StoredUpload(upload=raced, duplicate=True)
        raise
    session.expire(upload, ["extractions"])
    return StoredUpload(upload=get_upload(session, upload.id), duplicate=False)


def _extract(
    session: Session,
    upload: UploadedDocument,
    extractor: object,
    parsed: ParsedDocument,
) -> None:
    extract = getattr(extractor, "extract", None)
    if extract is None:
        _mark_upload_failed(
            upload,
            "extraction_failed",
            "The document could not be extracted. No procurement record was written.",
        )
        return
    try:
        outcome = extract(parsed)
    except DocumentExtractionError as exc:
        logger.warning("document_extraction_failed", extra={"error_type": type(exc).__name__})
        _record_extraction_failure(session, upload, extractor, exc)
        return
    except Exception as exc:
        logger.warning("document_extraction_failed", extra={"error_type": type(exc).__name__})
        if _preserve_upload(upload):
            raise ProcurementError(
                "extraction_failed",
                "The document could not be extracted. Stored records were not changed.",
                500,
            ) from exc
        _mark_upload_failed(
            upload,
            "extraction_failed",
            "The document could not be extracted. No procurement record was written.",
        )
        return
    checked = validate_extraction(outcome.document, outcome.prompt_injection_flags)
    extraction = DocumentExtraction(
        uploaded_document_id=upload.id,
        provider=outcome.provider,
        mocked=outcome.mocked,
        model_name=outcome.model_name,
        reasoning_kind=outcome.reasoning_kind,
        payload=outcome.document.model_dump(mode="json"),
        prompt_injection_flags=list(outcome.prompt_injection_flags),
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        estimated_cost_usd=outcome.estimated_cost_usd,
    )
    session.add(extraction)
    session.flush()
    session.add(
        ExtractionValidation(
            extraction_id=extraction.id,
            status=checked.status,
            blocking=checked.blocking,
            warnings=[item.model_dump(mode="json") for item in checked.warnings],
            normalized=None
            if checked.normalized is None
            else checked.normalized.model_dump(mode="json"),
            computed=checked.computed.model_dump(mode="json"),
        )
    )
    upload.updated_at = datetime.now(UTC)
    if upload.status != "accepted":
        upload.status = "needs_review"
        upload.error_code = None
        upload.error_detail = None
        upload.stages = ["received", "parsed", "extracted", "needs_review"]


def _record_extraction_failure(
    session: Session,
    upload: UploadedDocument,
    extractor: object,
    exc: DocumentExtractionError,
) -> None:
    preserve = _preserve_upload(upload)
    if exc.request_sent:
        _store_failed_extraction(session, upload, extractor, exc)
    elif preserve:
        raise ProcurementError(exc.code, exc.detail, 409) from exc
    if preserve:
        upload.updated_at = datetime.now(UTC)
        return
    _mark_upload_failed(upload, exc.code, exc.detail)


def _store_failed_extraction(
    session: Session,
    upload: UploadedDocument,
    extractor: object,
    exc: DocumentExtractionError,
) -> None:
    provider = getattr(extractor, "name", None)
    mocked = getattr(extractor, "mocked", None)
    reasoning_kind = getattr(extractor, "reasoning_kind", None)
    model_name = getattr(extractor, "model_name", None)
    consistent = (
        provider == "mock" and mocked is True and reasoning_kind == "deterministic_test_double"
    ) or (provider == "openai" and mocked is False and reasoning_kind == "language_model")
    if not consistent or not isinstance(model_name, str) or not model_name.strip():
        return
    session.add(
        DocumentExtraction(
            uploaded_document_id=upload.id,
            provider=provider,
            mocked=mocked,
            model_name=model_name[:64],
            reasoning_kind=reasoning_kind,
            payload={"recorded_failure": True},
            prompt_injection_flags=[],
            input_tokens=exc.input_tokens,
            output_tokens=exc.output_tokens,
            estimated_cost_usd=exc.estimated_cost_usd,
            error_code=exc.code[:64],
            error_detail=exc.detail,
        )
    )
    session.flush()


def _preserve_upload(upload: UploadedDocument) -> bool:
    if upload.status == "accepted":
        return True
    return any(item.error_code is None for item in upload.extractions)


def _mark_upload_failed(upload: UploadedDocument, code: str, detail: str) -> None:
    upload.status = "failed"
    upload.error_code = code
    upload.error_detail = detail
    upload.stages = ["received", "parsed", "failed"]
    upload.updated_at = datetime.now(UTC)


def _parsed_from_upload(upload: UploadedDocument) -> ParsedDocument:
    pages: list[ParsedPage] = []
    for page in sorted(upload.pages, key=lambda item: item.page_number):
        blocks: list[TextBlock] = []
        for block in page.blocks:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                continue
            raw_box = block.get("bbox")
            numeric = all(
                isinstance(item, (int, float)) and not isinstance(item, bool) for item in raw_box
            )
            if isinstance(raw_box, list) and len(raw_box) == 4 and numeric:
                box = (float(raw_box[0]), float(raw_box[1]), float(raw_box[2]), float(raw_box[3]))
            else:
                box = (0.0, 0.0, 0.0, 0.0)
            blocks.append(TextBlock(text=str(block["text"]), bbox=box))
        pages.append(ParsedPage(page_number=page.page_number, text=page.text, blocks=tuple(blocks)))
    return ParsedDocument(
        page_count=upload.page_count or len(pages),
        pages=tuple(pages),
        metadata={str(key): str(value) for key, value in upload.pdf_metadata.items()},
        image_only=upload.image_only,
        text_extractable=upload.text_extractable,
        char_count=upload.char_count,
    )


def _by_hash(session: Session, digest: str) -> UploadedDocument | None:
    upload_id = session.scalar(select(UploadedDocument.id).where(UploadedDocument.sha256 == digest))
    if upload_id is None:
        return None
    return get_upload(session, upload_id)


def _supplier_for_acceptance(session: Session, normalized: NormalizedDocument) -> Supplier:
    supplier = session.scalar(select(Supplier).where(Supplier.code == normalized.supplier_code))
    if supplier is None:
        supplier = Supplier(
            code=normalized.supplier_code,
            name=normalized.supplier_name,
            synthetic=False,
        )
        session.add(supplier)
        session.flush()
        return supplier
    if supplier.name != normalized.supplier_name:
        raise ConflictError(
            "supplier_identity_conflict",
            "A supplier with this code already exists under a different name. It was not changed.",
        )
    return supplier


def _case_has_purchase_order(session: Session, case_id: UUID) -> bool:
    found = session.scalar(select(PurchaseOrder.id).where(PurchaseOrder.case_id == case_id))
    return found is not None


def _commercial_exists(
    session: Session,
    supplier_id: UUID,
    document_type: DocumentType,
    number: str,
) -> bool:
    model = {
        DocumentType.PURCHASE_ORDER: PurchaseOrder,
        DocumentType.DELIVERY_NOTE: DeliveryNote,
        DocumentType.INVOICE: Invoice,
    }[document_type]
    found = session.scalar(
        select(model.id).where(model.supplier_id == supplier_id, model.number == number)
    )
    return found is not None


def _upload_case(
    session: Session, supplier_id: UUID, purchase_order_number: str | None
) -> ProcurementCase | None:
    if purchase_order_number is None:
        return None
    for model, column in (
        (PurchaseOrder, PurchaseOrder.number),
        (DeliveryNote, DeliveryNote.purchase_order_number),
        (Invoice, Invoice.purchase_order_number),
    ):
        case_id = session.scalar(
            select(model.case_id)
            .join(ProcurementCase, ProcurementCase.id == model.case_id)
            .where(
                model.supplier_id == supplier_id,
                column == purchase_order_number,
                ProcurementCase.origin == "upload",
                ProcurementCase.synthetic.is_(False),
            )
            .limit(1)
        )
        if case_id is not None:
            case = session.get(ProcurementCase, case_id)
            if case is not None:
                return case
    return None


def _unique_reference(session: Session, base: str) -> str:
    candidate = base[:64]
    for suffix in range(1, 20):
        reference = candidate if suffix == 1 else f"{base[:58]}-{suffix}"
        found = session.scalar(
            select(ProcurementCase.id).where(ProcurementCase.reference == reference)
        )
        if found is None:
            return reference
    raise ConflictError(
        "case_reference_conflict",
        "An upload case reference could not be allocated. No record was written.",
    )


def _insert_commercial(
    session: Session,
    case: ProcurementCase,
    supplier: Supplier,
    source: ProcurementDocument,
    document: NormalizedDocument,
) -> None:
    issued = date.fromisoformat(document.document_date)
    if document.document_type is DocumentType.PURCHASE_ORDER:
        if document.currency is None:
            raise ConflictError("extraction_not_acceptable", "The purchase order has no currency.")
        purchase_order = PurchaseOrder(
            case_id=case.id,
            supplier_id=supplier.id,
            source_document_id=source.id,
            number=document.document_number,
            currency=document.currency,
            issued_on=issued,
        )
        session.add(purchase_order)
        session.flush()
        for line in document.lines:
            if line.unit_price is None:
                raise ConflictError(
                    "extraction_not_acceptable", "A purchase-order line has no unit price."
                )
            session.add(
                PurchaseOrderLine(
                    purchase_order_id=purchase_order.id,
                    source_document_id=source.id,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=Decimal(line.quantity),
                    unit=line.unit,
                    unit_price=Decimal(line.unit_price),
                    currency=document.currency,
                )
            )
        return
    if document.document_type is DocumentType.DELIVERY_NOTE:
        note = DeliveryNote(
            case_id=case.id,
            supplier_id=supplier.id,
            source_document_id=source.id,
            number=document.document_number,
            purchase_order_number=document.purchase_order_number,
            delivered_on=issued,
        )
        session.add(note)
        session.flush()
        for line in document.lines:
            session.add(
                DeliveryNoteLine(
                    delivery_note_id=note.id,
                    source_document_id=source.id,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=Decimal(line.quantity),
                    unit=line.unit,
                )
            )
        return
    if document.currency is None:
        raise ConflictError("extraction_not_acceptable", "The invoice has no currency.")
    invoice = Invoice(
        case_id=case.id,
        supplier_id=supplier.id,
        source_document_id=source.id,
        number=document.document_number,
        purchase_order_number=document.purchase_order_number,
        currency=document.currency,
        issued_on=issued,
    )
    session.add(invoice)
    session.flush()
    for line in document.lines:
        if line.unit_price is None:
            raise ConflictError("extraction_not_acceptable", "An invoice line has no unit price.")
        session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                source_document_id=source.id,
                line_number=line.line_number,
                product_code=line.product_code,
                description=line.description,
                quantity=Decimal(line.quantity),
                unit=line.unit,
                unit_price=Decimal(line.unit_price),
                currency=document.currency,
            )
        )


def _reconcile(session: Session, case_id: UUID) -> tuple[UUID | None, str | None, str | None]:
    try:
        stored = run_reconciliation(session, case_id)
    except ProcurementError as exc:
        return None, None, exc.detail
    return stored.run.id, stored.run.status, None


def _replay_acceptance(session: Session, upload: UploadedDocument) -> AcceptedUpload:
    if upload.accepted_case_id is None:
        raise ConflictError(
            "document_not_acceptable",
            "This document is marked accepted but has no procurement case.",
        )
    case = session.get(ProcurementCase, upload.accepted_case_id)
    source_id = session.scalar(
        select(ProcurementDocument.id).where(ProcurementDocument.upload_id == upload.id)
    )
    if case is None or source_id is None:
        raise ConflictError(
            "document_not_acceptable",
            "The accepted procurement record could not be reloaded.",
        )
    reconciliation_id = None
    reconciliation_status = None
    try:
        run = latest_reconciliation(session, case.id)
    except NotFoundError:
        run = None
    if run is not None:
        reconciliation_id = run.id
        reconciliation_status = run.status
    return AcceptedUpload(
        upload=upload,
        case=case,
        procurement_document_id=source_id,
        replayed=True,
        reconciliation_id=reconciliation_id,
        reconciliation_status=reconciliation_status,
        reconciliation_error=None,
    )
