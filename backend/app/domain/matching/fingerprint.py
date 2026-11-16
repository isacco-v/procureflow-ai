"""Canonical fingerprint of a reconciliation input.

The same commercial records always hash to the same value. The engine version
is part of the hash, so a later change in comparison rules does not replay a
stale report.
"""

import hashlib
import json

from app.domain.decimals import format_decimal
from app.domain.matching.engine import ENGINE_VERSION
from app.domain.matching.models import ReconciliationInput


def fingerprint_input(data: ReconciliationInput) -> str:
    payload = {
        "documents": [
            {
                "currency": document.currency,
                "document_number": document.document_number,
                "document_type": document.document_type.value,
                "purchase_order_number": document.purchase_order_number,
            }
            for document in sorted(
                data.documents,
                key=lambda item: (item.document_type.value, item.document_number),
            )
        ],
        "engine_version": ENGINE_VERSION,
        "lines": [
            {
                "currency": line.currency,
                "description": line.description,
                "document_number": line.document_number,
                "document_type": line.document_type.value,
                "line_number": line.line_number,
                "product_code": line.product_code,
                "quantity": format_decimal(line.quantity),
                "unit": line.unit,
                "unit_price": None if line.unit_price is None else format_decimal(line.unit_price),
            }
            for line in sorted(
                data.lines,
                key=lambda item: (item.document_type.value, item.document_number, item.line_number),
            )
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
