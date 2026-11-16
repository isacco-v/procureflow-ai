"""Persist a pure reconciliation report for one procurement case.

Repeating the call with unchanged documents returns the stored run. The matcher
itself does not touch the session.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import ProcurementCase, ReconciliationFinding, ReconciliationRun
from app.domain.matching.engine import ENGINE_VERSION, prepare_input, reconcile
from app.domain.matching.fingerprint import fingerprint_input
from app.domain.matching.models import (
    DocumentType,
    ReconciliationInput,
    ReconciliationInputError,
    SourceDocument,
    SourceLine,
)
from app.services.cases import get_case
from app.services.errors import NotFoundError, ProcurementError

_RUN_OPTIONS = (selectinload(ReconciliationRun.findings),)


@dataclass(frozen=True)
class StoredReconciliation:
    run: ReconciliationRun
    created: bool


def run_reconciliation(session: Session, case_id: UUID) -> StoredReconciliation:
    case = get_case(session, case_id)
    try:
        prepared = prepare_input(_case_input(case))
    except ReconciliationInputError as exc:
        raise ProcurementError("invalid_reconciliation_input", str(exc), 422) from exc

    digest = fingerprint_input(prepared)
    existing = _find_run(session, case.id, digest)
    if existing is not None:
        return StoredReconciliation(run=existing, created=False)

    report = reconcile(prepared)
    documents = {
        (document.document_type, document.document_number): document.id
        for document in case.documents
    }
    run = ReconciliationRun(
        case_id=case.id,
        status=report.status.value,
        input_fingerprint=digest,
        engine_version=ENGINE_VERSION,
    )
    session.add(run)
    session.flush()
    for ordinal, finding in enumerate(report.findings, start=1):
        session.add(
            ReconciliationFinding(
                run_id=run.id,
                ordinal=ordinal,
                code=finding.code.value,
                status=finding.status.value,
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
                    {
                        "document_type": reference.document_type.value,
                        "document_number": reference.document_number,
                        "line_number": reference.line_number,
                        "document_id": _document_id(
                            documents, reference.document_type.value, reference.document_number
                        ),
                    }
                    for reference in finding.source_references
                ],
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _find_run(session, case_id, digest)
        if raced is not None:
            return StoredReconciliation(run=raced, created=False)
        raise
    stored = _find_run(session, case.id, digest)
    if stored is None:
        raise ProcurementError(
            "reconciliation_not_stored",
            "The reconciliation run could not be reloaded.",
            500,
        )
    return StoredReconciliation(run=stored, created=True)


def latest_reconciliation(session: Session, case_id: UUID) -> ReconciliationRun:
    get_case(session, case_id)
    run = session.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.case_id == case_id)
        .options(*_RUN_OPTIONS)
        .order_by(ReconciliationRun.created_at.desc(), ReconciliationRun.id.desc())
        .limit(1)
    )
    if run is None:
        raise NotFoundError(
            "reconciliation_not_found",
            "This case has no reconciliation run yet.",
        )
    return run


def get_reconciliation(session: Session, case_id: UUID, run_id: UUID) -> ReconciliationRun:
    get_case(session, case_id)
    run = session.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.id == run_id, ReconciliationRun.case_id == case_id)
        .options(*_RUN_OPTIONS)
    )
    if run is None:
        raise NotFoundError("reconciliation_not_found", "Reconciliation run was not found.")
    return run


def _find_run(session: Session, case_id: UUID, digest: str) -> ReconciliationRun | None:
    return session.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.case_id == case_id,
            ReconciliationRun.input_fingerprint == digest,
        )
        .options(*_RUN_OPTIONS)
    )


def _document_id(
    documents: dict[tuple[str, str], UUID],
    document_type: str,
    document_number: str,
) -> str | None:
    document_id = documents.get((document_type, document_number))
    if document_id is None:
        return None
    return str(document_id)


def _case_input(case: ProcurementCase) -> ReconciliationInput:
    documents: list[SourceDocument] = []
    lines: list[SourceLine] = []
    purchase_order = case.purchase_order
    if purchase_order is not None:
        documents.append(
            SourceDocument(
                document_type=DocumentType.PURCHASE_ORDER,
                document_number=purchase_order.number,
                purchase_order_number=purchase_order.number,
                currency=purchase_order.currency,
            )
        )
        for line in purchase_order.lines:
            lines.append(
                SourceLine(
                    document_type=DocumentType.PURCHASE_ORDER,
                    document_number=purchase_order.number,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    currency=line.currency,
                )
            )
    for note in sorted(case.delivery_notes, key=lambda item: item.number):
        documents.append(
            SourceDocument(
                document_type=DocumentType.DELIVERY_NOTE,
                document_number=note.number,
                purchase_order_number=note.purchase_order_number,
                currency=None,
            )
        )
        for line in note.lines:
            lines.append(
                SourceLine(
                    document_type=DocumentType.DELIVERY_NOTE,
                    document_number=note.number,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=None,
                    currency=None,
                )
            )
    for invoice in sorted(case.invoices, key=lambda item: item.number):
        documents.append(
            SourceDocument(
                document_type=DocumentType.INVOICE,
                document_number=invoice.number,
                purchase_order_number=invoice.purchase_order_number,
                currency=invoice.currency,
            )
        )
        for line in invoice.lines:
            lines.append(
                SourceLine(
                    document_type=DocumentType.INVOICE,
                    document_number=invoice.number,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=line.unit_price,
                    currency=line.currency,
                )
            )
    return ReconciliationInput(documents=documents, lines=lines)
