"""Idempotent insert of the synthetic procurement scenarios.

An existing case reference is left unchanged, including any reconciliation runs
already stored for it. A second call does not create duplicate rows.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DeliveryNote,
    DeliveryNoteLine,
    Invoice,
    InvoiceLine,
    ProcurementCase,
    ProcurementDocument,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.domain.matching.models import DocumentType
from app.domain.scenarios import SCENARIOS, DocumentFixture, ScenarioFixture
from app.services.errors import SeedUnavailableError
from app.services.identifiers import synthetic_id
from app.services.policy_seed import ensure_policy_corpus

SEED_ENVIRONMENTS = frozenset({"local", "test", "development"})


class SeedResult:
    def __init__(self, created: tuple[str, ...], existing: tuple[str, ...]) -> None:
        self.created = created
        self.existing = existing


def assert_seed_allowed(app_env: str) -> None:
    if app_env not in SEED_ENVIRONMENTS:
        raise SeedUnavailableError()


def seed_synthetic_cases(session: Session) -> SeedResult:
    created: list[str] = []
    existing: list[str] = []
    for scenario in SCENARIOS:
        found = session.scalar(
            select(ProcurementCase.id).where(ProcurementCase.reference == scenario.reference)
        )
        if found is not None:
            existing.append(scenario.reference)
            continue
        _insert_scenario(session, scenario)
        created.append(scenario.reference)
    ensure_policy_corpus(session)
    session.commit()
    return SeedResult(created=tuple(created), existing=tuple(existing))


def _insert_scenario(session: Session, scenario: ScenarioFixture) -> None:
    supplier = session.scalar(select(Supplier).where(Supplier.code == scenario.supplier.code))
    if supplier is None:
        supplier = Supplier(
            id=synthetic_id(f"supplier:{scenario.supplier.code}"),
            code=scenario.supplier.code,
            name=scenario.supplier.name,
            synthetic=True,
        )
        session.add(supplier)
        session.flush()

    case = ProcurementCase(
        id=synthetic_id(f"case:{scenario.reference}"),
        reference=scenario.reference,
        title=scenario.title,
        summary=scenario.summary,
        synthetic=True,
        origin="synthetic_seed",
        supplier_id=supplier.id,
    )
    session.add(case)
    session.flush()

    for document in scenario.documents:
        source = ProcurementDocument(
            id=synthetic_id(f"document:{scenario.reference}:{document.document_number}"),
            case_id=case.id,
            document_type=document.document_type.value,
            document_number=document.document_number,
            synthetic=True,
            origin="synthetic_seed",
        )
        session.add(source)
        session.flush()
        _insert_commercial_document(session, case, supplier, source, document)


def _insert_commercial_document(
    session: Session,
    case: ProcurementCase,
    supplier: Supplier,
    source: ProcurementDocument,
    document: DocumentFixture,
) -> None:
    if document.document_type is DocumentType.PURCHASE_ORDER:
        purchase_order = PurchaseOrder(
            id=synthetic_id(f"purchase-order:{document.document_number}"),
            case_id=case.id,
            supplier_id=supplier.id,
            source_document_id=source.id,
            number=document.document_number,
            currency=document.currency or "",
            issued_on=document.document_date,
        )
        session.add(purchase_order)
        session.flush()
        for line in document.lines:
            session.add(
                PurchaseOrderLine(
                    id=synthetic_id(
                        f"purchase-order-line:{document.document_number}:{line.line_number}"
                    ),
                    purchase_order_id=purchase_order.id,
                    source_document_id=source.id,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                    unit_price=_required_price(line.unit_price, document.document_number),
                    currency=line.currency or purchase_order.currency,
                )
            )
        return

    if document.document_type is DocumentType.DELIVERY_NOTE:
        delivery = DeliveryNote(
            id=synthetic_id(f"delivery-note:{document.document_number}"),
            case_id=case.id,
            supplier_id=supplier.id,
            source_document_id=source.id,
            number=document.document_number,
            purchase_order_number=document.purchase_order_number,
            delivered_on=document.document_date,
        )
        session.add(delivery)
        session.flush()
        for line in document.lines:
            session.add(
                DeliveryNoteLine(
                    id=synthetic_id(f"delivery-line:{document.document_number}:{line.line_number}"),
                    delivery_note_id=delivery.id,
                    source_document_id=source.id,
                    line_number=line.line_number,
                    product_code=line.product_code,
                    description=line.description,
                    quantity=line.quantity,
                    unit=line.unit,
                )
            )
        return

    invoice = Invoice(
        id=synthetic_id(f"invoice:{document.document_number}"),
        case_id=case.id,
        supplier_id=supplier.id,
        source_document_id=source.id,
        number=document.document_number,
        purchase_order_number=document.purchase_order_number,
        currency=document.currency or "",
        issued_on=document.document_date,
    )
    session.add(invoice)
    session.flush()
    for line in document.lines:
        session.add(
            InvoiceLine(
                id=synthetic_id(f"invoice-line:{document.document_number}:{line.line_number}"),
                invoice_id=invoice.id,
                source_document_id=source.id,
                line_number=line.line_number,
                product_code=line.product_code,
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=_required_price(line.unit_price, document.document_number),
                currency=line.currency or invoice.currency,
            )
        )


def _required_price(value: Decimal | None, document_number: str) -> Decimal:
    if value is None:
        raise ValueError(f"{document_number} is missing a unit price.")
    return value
