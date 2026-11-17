"""Synthetic procurement policy corpus.

Each policy is one versioned, citable section. The text is fictional and is
the source for lexical retrieval. It is not a legal opinion.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PolicyFixture:
    code: str
    title: str
    version: str
    effective_on: date
    heading: str
    body: str


_EFFECTIVE = date(2026, 1, 15)

POLICY_CORPUS: tuple[PolicyFixture, ...] = (
    PolicyFixture(
        code="POL-DEL-001",
        title="Partial deliveries",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Accepting a partial delivery",
        body=(
            "A partial delivery is a delivery note whose received quantity is lower than "
            "the purchase-order quantity, with the remainder still open. The received "
            "quantity is the sum of delivery-note lines that share the purchase-order "
            "product code. The invoice quantity for that product must not exceed the "
            "received quantity unless a person records a contract exception on the case. "
            "The undelivered balance stays open on the purchase order. Software must not "
            "treat a partial delivery as a complete delivery."
        ),
    ),
    PolicyFixture(
        code="POL-QTY-001",
        title="Quantity discrepancies",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Quantity differences between delivery and invoice",
        body=(
            "A quantity discrepancy exists when the invoiced quantity and the delivered "
            "quantity for the same product code differ by more than the configured "
            "tolerance. The matcher quantities are authoritative. An investigation must "
            "not recompute them. Do not accept an invoice quantity that was not delivered. "
            "Ask the supplier for a credit note or a revised invoice for the undelivered "
            "quantity. A person reviews the case before any financial decision."
        ),
    ),
    PolicyFixture(
        code="POL-PRICE-001",
        title="Price discrepancies",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Unit price differences",
        body=(
            "The invoice unit price is compared with the purchase-order unit price in the "
            "same currency. A price discrepancy is the invoice unit price minus the "
            "purchase-order unit price. A higher invoice price is not accepted "
            "automatically. Hold the invoice for price review. The buyer may ask the "
            "supplier for a credit note. A person decides whether a previously agreed "
            "variance exists. The investigation must not accept the price difference."
        ),
    ),
    PolicyFixture(
        code="POL-APR-001",
        title="Invoice approval requirements",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Who may approve an invoice",
        body=(
            "Invoice approval is a human decision. It may be considered only when the "
            "reconciliation status is MATCHED. A status of EXCEPTION or NEEDS_REVIEW "
            "cannot be approved by software. This system does not initiate payment, post "
            "to an ERP, or change the reconciliation result. A person records an approval, "
            "a rejection, or a request for another investigation as a separate review action."
        ),
    ),
    PolicyFixture(
        code="POL-PROD-001",
        title="Missing or ambiguous product references",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Product identity",
        body=(
            "The product code is the only identifier that authorizes a financial "
            "comparison. A missing product code is unresolved. Similar or identical "
            "descriptions do not establish that two lines are the same product. An "
            "ambiguous product reference or an uncertain product mapping stops the "
            "financial comparison for those lines. Escalate the identity question to a "
            "person. Do not merge the lines and do not invent a product code."
        ),
    ),
    PolicyFixture(
        code="POL-SUP-001",
        title="Supplier clarification procedures",
        version="1.0",
        effective_on=_EFFECTIVE,
        heading="Asking the supplier to clarify",
        body=(
            "When a discrepancy needs an explanation, send the supplier a written "
            "clarification request. Quote the purchase-order number, the delivery-note "
            "numbers, the invoice number, and the discrepancy recorded by the matcher. "
            "Do not pay the invoice while supplier clarification is open. Keep the reply "
            "with the case. A person reviews the reply before the case can change status."
        ),
    ),
)
