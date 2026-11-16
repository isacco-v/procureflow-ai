"""Load procurement cases for the API."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    DeliveryNote,
    Invoice,
    ProcurementCase,
    PurchaseOrder,
    ReconciliationRun,
    Supplier,
)
from app.services.errors import NotFoundError

_CASE_OPTIONS = (
    selectinload(ProcurementCase.supplier),
    selectinload(ProcurementCase.documents),
    selectinload(ProcurementCase.purchase_order).selectinload(PurchaseOrder.lines),
    selectinload(ProcurementCase.delivery_notes).selectinload(DeliveryNote.lines),
    selectinload(ProcurementCase.invoices).selectinload(Invoice.lines),
    selectinload(ProcurementCase.reconciliation_runs),
)


@dataclass(frozen=True)
class CaseListRow:
    case: ProcurementCase
    supplier: Supplier
    latest_run_id: UUID | None
    latest_status: str | None


def list_cases(session: Session) -> list[CaseListRow]:
    latest = (
        select(
            ReconciliationRun.case_id.label("case_id"),
            ReconciliationRun.id.label("run_id"),
            ReconciliationRun.status.label("status"),
        )
        .ext(distinct_on(ReconciliationRun.case_id))
        .order_by(
            ReconciliationRun.case_id,
            ReconciliationRun.created_at.desc(),
            ReconciliationRun.id.desc(),
        )
        .subquery()
    )
    rows = session.execute(
        select(ProcurementCase, Supplier, latest.c.run_id, latest.c.status)
        .join(Supplier, ProcurementCase.supplier_id == Supplier.id)
        .outerjoin(latest, latest.c.case_id == ProcurementCase.id)
        .order_by(ProcurementCase.reference)
    ).all()
    return [
        CaseListRow(case=case, supplier=supplier, latest_run_id=run_id, latest_status=status)
        for case, supplier, run_id, status in rows
    ]


def get_case(session: Session, case_id: UUID) -> ProcurementCase:
    case = session.scalar(
        select(ProcurementCase).where(ProcurementCase.id == case_id).options(*_CASE_OPTIONS)
    )
    if case is None:
        raise NotFoundError("case_not_found", "Procurement case was not found.")
    return case
