"""Importing this package registers the domain tables on the SQLAlchemy metadata."""

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

__all__ = [
    "DeliveryNote",
    "DeliveryNoteLine",
    "Invoice",
    "InvoiceLine",
    "ProcurementCase",
    "ProcurementDocument",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "ReconciliationFinding",
    "ReconciliationRun",
    "Supplier",
]
