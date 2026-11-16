"""Map persisted procurement rows to API models."""

from uuid import UUID

from app.db.models import (
    DeliveryNote,
    DeliveryNoteLine,
    Invoice,
    InvoiceLine,
    ProcurementCase,
    PurchaseOrder,
    PurchaseOrderLine,
    ReconciliationFinding,
    ReconciliationRun,
)
from app.domain.matching.models import MatchStatus
from app.schemas.procurement import (
    CaseDetailResponse,
    CaseSummaryResponse,
    DeliveryNoteResponse,
    DocumentLineResponse,
    FindingResponse,
    InvoiceResponse,
    PurchaseOrderResponse,
    ReconciliationResponse,
    SourceDocumentResponse,
    SourceReferenceResponse,
    SupplierResponse,
)
from app.services.cases import CaseListRow


def case_summary(row: CaseListRow) -> CaseSummaryResponse:
    return _summary(
        row.case,
        latest_reconciliation_id=row.latest_run_id,
        latest_reconciliation_status=(
            None if row.latest_status is None else MatchStatus(row.latest_status)
        ),
    )


def case_detail(case: ProcurementCase, latest: ReconciliationRun | None) -> CaseDetailResponse:
    summary = _summary(
        case,
        latest_reconciliation_id=None if latest is None else latest.id,
        latest_reconciliation_status=None if latest is None else MatchStatus(latest.status),
    )
    return CaseDetailResponse(
        **summary.model_dump(),
        documents=[
            SourceDocumentResponse(
                id=document.id,
                document_type=document.document_type,
                document_number=document.document_number,
                synthetic=document.synthetic,
            )
            for document in sorted(case.documents, key=lambda item: item.document_number)
        ],
        purchase_order=None
        if case.purchase_order is None
        else _purchase_order(case.purchase_order),
        delivery_notes=[
            _delivery(note) for note in sorted(case.delivery_notes, key=lambda item: item.number)
        ],
        invoices=[
            _invoice(invoice) for invoice in sorted(case.invoices, key=lambda item: item.number)
        ],
    )


def reconciliation_response(run: ReconciliationRun, *, replayed: bool) -> ReconciliationResponse:
    return ReconciliationResponse(
        id=run.id,
        case_id=run.case_id,
        status=MatchStatus(run.status),
        engine_version=run.engine_version,
        input_fingerprint=run.input_fingerprint,
        created_at=run.created_at,
        replayed=replayed,
        findings=[
            _finding(finding) for finding in sorted(run.findings, key=lambda item: item.ordinal)
        ],
    )


def _summary(
    case: ProcurementCase,
    *,
    latest_reconciliation_id: UUID | None,
    latest_reconciliation_status: MatchStatus | None,
) -> CaseSummaryResponse:
    supplier = case.supplier
    return CaseSummaryResponse(
        id=case.id,
        reference=case.reference,
        title=case.title,
        summary=case.summary,
        synthetic=case.synthetic,
        supplier=SupplierResponse(
            id=supplier.id,
            code=supplier.code,
            name=supplier.name,
            synthetic=supplier.synthetic,
        ),
        latest_reconciliation_id=latest_reconciliation_id,
        latest_reconciliation_status=latest_reconciliation_status,
    )


def _purchase_order(purchase_order: PurchaseOrder) -> PurchaseOrderResponse:
    return PurchaseOrderResponse(
        id=purchase_order.id,
        number=purchase_order.number,
        currency=purchase_order.currency,
        issued_on=purchase_order.issued_on,
        source_document_id=purchase_order.source_document_id,
        lines=[_priced_line(line) for line in purchase_order.lines],
    )


def _delivery(note: DeliveryNote) -> DeliveryNoteResponse:
    return DeliveryNoteResponse(
        id=note.id,
        number=note.number,
        purchase_order_number=note.purchase_order_number,
        delivered_on=note.delivered_on,
        source_document_id=note.source_document_id,
        lines=[_quantity_line(line) for line in note.lines],
    )


def _invoice(invoice: Invoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        number=invoice.number,
        purchase_order_number=invoice.purchase_order_number,
        currency=invoice.currency,
        issued_on=invoice.issued_on,
        source_document_id=invoice.source_document_id,
        lines=[_priced_line(line) for line in invoice.lines],
    )


def _priced_line(line: PurchaseOrderLine | InvoiceLine) -> DocumentLineResponse:
    return DocumentLineResponse(
        line_number=line.line_number,
        product_code=line.product_code,
        description=line.description,
        quantity=line.quantity,
        unit=line.unit,
        unit_price=line.unit_price,
        currency=line.currency,
        source_document_id=line.source_document_id,
    )


def _quantity_line(line: DeliveryNoteLine) -> DocumentLineResponse:
    return DocumentLineResponse(
        line_number=line.line_number,
        product_code=line.product_code,
        description=line.description,
        quantity=line.quantity,
        unit=line.unit,
        source_document_id=line.source_document_id,
    )


def _finding(finding: ReconciliationFinding) -> FindingResponse:
    return FindingResponse(
        code=finding.code,
        status=finding.status,
        product_code=finding.product_code,
        message=finding.message,
        unit=finding.unit,
        currency=finding.currency,
        ordered_quantity=finding.ordered_quantity,
        delivered_quantity=finding.delivered_quantity,
        invoiced_quantity=finding.invoiced_quantity,
        quantity_difference=finding.quantity_difference,
        purchase_order_unit_price=finding.purchase_order_unit_price,
        invoice_unit_price=finding.invoice_unit_price,
        price_difference=finding.price_difference,
        source_references=[
            SourceReferenceResponse.model_validate(item) for item in finding.source_references
        ],
    )
