"""Importing this package registers the domain tables on the SQLAlchemy metadata."""

from app.db.models.investigation import (
    Investigation,
    InvestigationCitation,
    InvestigationEvent,
    InvestigationEvidence,
    PolicyDocument,
    PolicySection,
)
from app.db.models.procurement import (
    DeliveryNote,
    DeliveryNoteLine,
    Invoice,
    InvoiceLine,
    ProcurementCase,
    ProcurementDocument,
    PurchaseOrder,
    PurchaseOrderLine,
    ReconciliationFinding,
    ReconciliationRun,
    Supplier,
)
from app.db.models.uploads import (
    DocumentExtraction,
    DocumentPage,
    ExtractionValidation,
    UploadedDocument,
)

__all__ = [
    "DeliveryNote",
    "DocumentExtraction",
    "DocumentPage",
    "ExtractionValidation",
    "DeliveryNoteLine",
    "Investigation",
    "InvestigationCitation",
    "InvestigationEvidence",
    "InvestigationEvent",
    "Invoice",
    "InvoiceLine",
    "PolicyDocument",
    "PolicySection",
    "ProcurementCase",
    "ProcurementDocument",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "ReconciliationFinding",
    "ReconciliationRun",
    "Supplier",
    "UploadedDocument",
]
