"""Map persisted procurement rows to API models."""

from uuid import UUID

from app.db.models import (
    DeliveryNote,
    DeliveryNoteLine,
    Investigation,
    InvestigationEvent,
    Invoice,
    InvoiceLine,
    ProcurementCase,
    PurchaseOrder,
    PurchaseOrderLine,
    ReconciliationFinding,
    ReconciliationRun,
)
from app.domain.investigation import InvestigationStatus, ReasoningKind, RecommendedAction
from app.domain.matching.models import MatchStatus
from app.schemas.investigation import (
    InvestigationCitationResponse,
    InvestigationEventListResponse,
    InvestigationEventResponse,
    InvestigationEvidenceResponse,
    InvestigationFindingResponse,
    InvestigationResponse,
)
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
                origin=document.origin,  # type: ignore[arg-type]
                upload_id=document.upload_id,
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
        origin=case.origin,  # type: ignore[arg-type]
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


def investigation_response(
    investigation: Investigation, *, replayed: bool
) -> InvestigationResponse:
    reasoning = ReasoningKind(investigation.reasoning_kind)
    action = investigation.recommended_action
    return InvestigationResponse(
        id=investigation.id,
        case_id=investigation.case_id,
        reconciliation_run_id=investigation.reconciliation_run_id,
        status=InvestigationStatus(investigation.status),
        ai_mode="openai" if investigation.ai_mode == "openai" else "mock",
        provider=investigation.provider,
        model_name=investigation.model_name,
        reasoning_kind=reasoning,
        mock_execution=reasoning is ReasoningKind.DETERMINISTIC_TEST_DOUBLE,
        recommended_action=None if action is None else RecommendedAction(action),
        review_required=True,
        summary=investigation.summary,
        findings=[
            InvestigationFindingResponse.model_validate(item)
            for item in investigation.structured_findings
        ],
        unresolved_issues=list(investigation.unresolved_issues),
        citations=[
            InvestigationCitationResponse(
                policy_code=citation.policy_code,
                section_code=citation.section_code,
                version=citation.version,
                heading=citation.heading,
                excerpt=citation.excerpt,
            )
            for citation in investigation.citations
        ],
        evidence=[
            InvestigationEvidenceResponse(
                tool_name=item.tool_name,
                record_type=item.record_type,
                record_id=item.record_id,
                label=item.label,
            )
            for item in investigation.evidence
        ],
        events=[_investigation_event(event) for event in investigation.events],
        error_code=investigation.error_code,
        error_detail=investigation.error_detail,
        input_tokens=investigation.input_tokens,
        output_tokens=investigation.output_tokens,
        estimated_cost_usd=investigation.estimated_cost_usd,
        iteration_count=investigation.iteration_count,
        tool_call_count=investigation.tool_call_count,
        attempt=investigation.attempt,
        evidence_validated=investigation.evidence_validated is True,
        observed_facts=list(investigation.observed_facts or []),
        possible_explanations=list(investigation.possible_explanations or []),
        missing_evidence=list(investigation.missing_evidence or []),
        next_actions=list(investigation.next_actions or []),
        replayed=replayed,
        started_at=investigation.started_at,
        finished_at=investigation.finished_at,
    )


def investigation_events(investigation: Investigation) -> InvestigationEventListResponse:
    return InvestigationEventListResponse(
        investigation_id=investigation.id,
        events=[_investigation_event(event) for event in investigation.events],
    )


def _investigation_event(event: InvestigationEvent) -> InvestigationEventResponse:
    return InvestigationEventResponse(
        ordinal=event.ordinal,
        event_type=event.event_type,
        tool_name=event.tool_name,
        summary=event.summary,
        payload=dict(event.payload),
        created_at=event.created_at,
    )
