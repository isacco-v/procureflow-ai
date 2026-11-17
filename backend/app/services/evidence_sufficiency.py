"""Deterministic evidence check for a proposed investigation outcome.

The check reads tool payloads. A document number that appears only inside a
matcher finding is an identifier, not a retrieved line. The check does not
choose which tool to call next and it does not invent a missing record.
"""

from dataclasses import dataclass
from typing import Any

from app.domain.investigation import EvidenceGap, RecommendationDraft

_QUANTITY = frozenset(
    {
        "ORDERED_NOT_DELIVERED",
        "DELIVERED_NOT_ORDERED",
        "INVOICED_WITHOUT_DELIVERY",
        "DELIVERED_NOT_INVOICED",
        "INVOICED_NOT_ORDERED",
        "ORDERED_NOT_INVOICED",
    }
)
_PRICE = frozenset({"PRICE_MISMATCH", "INCONSISTENT_UNIT_PRICE", "MISSING_UNIT_PRICE"})
_PRODUCT = frozenset({"UNCERTAIN_PRODUCT_MAPPING"})
_CONFIDENT = frozenset(
    {
        "request_quantity_credit",
        "hold_for_price_review",
        "escalate_product_identity",
        "request_supplier_clarification",
    }
)
_QUANTITY_POLICY = "POL-QTY-001"
_PRICE_POLICY = "POL-PRICE-001"
_PRODUCT_POLICY = "POL-PROD-001"
_DOCUMENT_TOOLS = {
    "purchase_order": "get_purchase_order",
    "delivery_note": "get_delivery_notes",
    "invoice": "get_invoices",
}
_CONDITIONAL_MARKERS = (
    "may still be delivered",
    "might still be delivered",
    "remaining quantity may",
    "balance may remain open",
    "does not establish that the remaining",
    "does not establish that the balance",
    "do not show that the remaining",
    "does not show that the remaining",
    "does not show that the balance",
    "if the supplier confirms",
    "only if the supplier",
    "conditional on",
    "pending confirmation",
    "delivery status is uncertain",
)


@dataclass(frozen=True)
class RetrievedLine:
    document_type: str
    document_number: str
    product_code: str | None
    description: str | None
    quantity: str | None
    unit_price: str | None
    product_code_observed: bool


@dataclass(frozen=True)
class EvidenceAssessment:
    gaps: tuple[EvidenceGap, ...]

    @property
    def sufficient(self) -> bool:
        return not self.gaps

    @property
    def details(self) -> list[str]:
        return [gap.detail for gap in self.gaps]


def assess_evidence(
    *,
    case_id: str,
    reconciliation_run_id: str,
    tool_results: list[dict[str, Any]],
    recommendation: RecommendationDraft | dict[str, Any] | None,
) -> EvidenceAssessment:
    """Return the evidence categories a proposed outcome still lacks."""

    draft = _draft(recommendation)
    findings = _findings(tool_results, case_id, reconciliation_run_id)
    lines = _lines(tool_results, case_id)
    policies = _policies(tool_results)
    gaps: list[EvidenceGap] = []
    quantity = [row for row in findings if row.get("code") in _QUANTITY]
    price = [row for row in findings if row.get("code") in _PRICE]
    product = [row for row in findings if row.get("code") in _PRODUCT]
    confident = draft is not None and draft.action.value in _CONFIDENT
    if confident and not (quantity or price or product):
        gaps.append(
            _gap(
                "reconciliation_findings",
                "Findings for this reconciliation run were not retrieved.",
            )
        )
    for row in quantity:
        gaps.extend(_quantity_gaps(row, lines, policies))
    for row in price:
        gaps.extend(_price_gaps(row, lines, policies))
    for row in product:
        gaps.extend(_product_gaps(row, lines, policies, draft))
    if quantity and draft is not None and draft.action.value == "request_quantity_credit":
        if not _credit_is_conditional(_recommendation_text(draft)):
            gaps.append(
                _gap(
                    "conditional_credit",
                    "A quantity credit must stay conditional. The retrieved delivery "
                    "records do not show that the remaining quantity will never be delivered.",
                    product_code=_text(quantity[0].get("product_code")),
                )
            )
    return EvidenceAssessment(tuple(_unique(gaps)))


def _draft(
    recommendation: RecommendationDraft | dict[str, Any] | None,
) -> RecommendationDraft | None:
    if recommendation is None:
        return None
    if isinstance(recommendation, RecommendationDraft):
        return recommendation
    return RecommendationDraft.model_validate(recommendation)


def _quantity_gaps(
    finding: dict[str, Any],
    lines: list[RetrievedLine],
    policies: set[str],
) -> list[EvidenceGap]:
    product = _text(finding.get("product_code"))
    gaps = [
        *_document_gaps(
            finding,
            lines,
            document_type="purchase_order",
            category="purchase_order_line",
            product_code=product,
            require_quantity=True,
        ),
        *_document_gaps(
            finding,
            lines,
            document_type="delivery_note",
            category="delivery_note_line",
            product_code=product,
            require_quantity=True,
        ),
        *_document_gaps(
            finding,
            lines,
            document_type="invoice",
            category="invoice_line",
            product_code=product,
            require_quantity=True,
        ),
    ]
    if _QUANTITY_POLICY not in policies:
        gaps.append(
            _gap(
                "policy",
                f"Applicable policy {_QUANTITY_POLICY} was not retrieved.",
                product_code=product,
            )
        )
    return gaps


def _price_gaps(
    finding: dict[str, Any],
    lines: list[RetrievedLine],
    policies: set[str],
) -> list[EvidenceGap]:
    product = _text(finding.get("product_code"))
    gaps = [
        *_document_gaps(
            finding,
            lines,
            document_type="purchase_order",
            category="purchase_order_line",
            product_code=product,
            require_price=True,
        ),
        *_document_gaps(
            finding,
            lines,
            document_type="invoice",
            category="invoice_line",
            product_code=product,
            require_price=True,
        ),
    ]
    if _PRICE_POLICY not in policies:
        gaps.append(
            _gap(
                "policy",
                f"Applicable policy {_PRICE_POLICY} was not retrieved.",
                product_code=product,
            )
        )
    return gaps


def _product_gaps(
    finding: dict[str, Any],
    lines: list[RetrievedLine],
    policies: set[str],
    draft: RecommendationDraft | None,
) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    references = _references(finding)
    relevant = references or _fallback_product_references(lines)
    described = [
        line
        for line in lines
        if line.description and line.product_code_observed and _reference_matches(line, relevant)
    ]
    if not described:
        gaps.append(
            _gap(
                "source_line_description",
                "Source line descriptions and identifiers were not retrieved.",
            )
        )
        gaps.append(
            _gap(
                "product_reference",
                "Product-reference fields were not retrieved on the source lines.",
            )
        )
    elif not all(line.product_code_observed for line in described):
        gaps.append(
            _gap(
                "product_reference",
                "A retrieved source line did not include its product-reference field.",
            )
        )
    missing_numbers = _missing_reference_numbers(relevant, described)
    if missing_numbers:
        gaps.append(
            _gap(
                "source_line_description",
                "Source lines were not retrieved for " + ", ".join(missing_numbers) + ".",
                document_numbers=missing_numbers,
            )
        )
    if _PRODUCT_POLICY not in policies:
        gaps.append(_gap("policy", f"Applicable policy {_PRODUCT_POLICY} was not retrieved."))
    text = "" if draft is None else _recommendation_text(draft)
    action = "" if draft is None else draft.action.value
    if not _uncertainty_is_explicit(action, text):
        gaps.append(
            _gap(
                "explicit_uncertainty",
                "Product equivalence is not established. The outcome must say so.",
            )
        )
    return gaps


def _document_gaps(
    finding: dict[str, Any],
    lines: list[RetrievedLine],
    *,
    document_type: str,
    category: str,
    product_code: str | None,
    require_quantity: bool = False,
    require_price: bool = False,
) -> list[EvidenceGap]:
    references = [
        item for item in _references(finding) if item.get("document_type") == document_type
    ]
    matched = [
        line
        for line in lines
        if line.document_type == document_type and _product_matches(line, product_code)
    ]
    if require_quantity:
        matched = [line for line in matched if line.quantity is not None]
    if require_price:
        matched = [line for line in matched if line.unit_price is not None]
    tool_name = _DOCUMENT_TOOLS[document_type]
    label = document_type.replace("_", " ")
    if not references:
        if matched:
            return []
        return [
            _gap(
                category,
                f"No {label} line for product {product_code or 'the finding'} was retrieved "
                f"for this case ({tool_name}).",
                product_code=product_code,
            )
        ]
    missing = [
        str(item["document_number"])
        for item in references
        if isinstance(item.get("document_number"), str)
        and not any(line.document_number == item["document_number"] for line in matched)
    ]
    if not missing:
        return []
    return [
        _gap(
            category,
            f"No {label} line for {', '.join(missing)} and product "
            f"{product_code or 'the finding'} was retrieved ({tool_name}).",
            product_code=product_code,
            document_numbers=missing,
        )
    ]


def _findings(
    tool_results: list[dict[str, Any]],
    case_id: str,
    reconciliation_run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in tool_results:
        if result.get("tool_name") != "get_reconciliation_findings" or not result.get("ok"):
            continue
        if _case_owner(result) != case_id or _run_owner(result) != reconciliation_run_id:
            continue
        data = result.get("data")
        raw = data.get("findings") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            continue
        rows.extend(item for item in raw if isinstance(item, dict))
    return rows


def _lines(tool_results: list[dict[str, Any]], case_id: str) -> list[RetrievedLine]:
    collected: list[RetrievedLine] = []
    for result in tool_results:
        if not result.get("ok") or result.get("found") is False:
            continue
        if _case_owner(result) != case_id:
            continue
        name = result.get("tool_name")
        data = result.get("data")
        if not isinstance(data, dict):
            continue
        if name == "get_purchase_order":
            document = data.get("purchase_order")
            documents = [document] if isinstance(document, dict) else []
            document_type = "purchase_order"
        elif name == "get_delivery_notes":
            documents = data.get("delivery_notes")
            document_type = "delivery_note"
        elif name == "get_invoices":
            documents = data.get("invoices")
            document_type = "invoice"
        else:
            continue
        if not isinstance(documents, list):
            continue
        for document in documents:
            if not isinstance(document, dict):
                continue
            number = document.get("number")
            raw_lines = document.get("lines")
            if not isinstance(raw_lines, list):
                continue
            for line in raw_lines:
                parsed = _line(line, document_type, number)
                if parsed is not None:
                    collected.append(parsed)
    return collected


def _line(line: object, document_type: str, number: object) -> RetrievedLine | None:
    if not isinstance(line, dict) or "line_number" not in line:
        return None
    document_number = line.get("document_number") or number
    if not isinstance(document_number, str) or not document_number:
        return None
    product = line.get("product_code")
    description = line.get("description")
    return RetrievedLine(
        document_type=document_type,
        document_number=document_number,
        product_code=product if isinstance(product, str) and product else None,
        description=description if isinstance(description, str) and description else None,
        quantity=_present(line.get("quantity")),
        unit_price=_present(line.get("unit_price")),
        product_code_observed="product_code" in line,
    )


def _policies(tool_results: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for result in tool_results:
        if result.get("tool_name") != "search_procurement_policy" or not result.get("ok"):
            continue
        data = result.get("data")
        raw = data.get("sections") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            continue
        for section in raw:
            if isinstance(section, dict) and isinstance(section.get("section_code"), str):
                found.add(section["section_code"])
    return found


def _references(finding: dict[str, Any]) -> list[dict[str, Any]]:
    raw = finding.get("source_references")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _fallback_product_references(lines: list[RetrievedLine]) -> list[dict[str, Any]]:
    return [
        {"document_type": line.document_type, "document_number": line.document_number}
        for line in lines
        if line.description
    ]


def _reference_matches(line: RetrievedLine, references: list[dict[str, Any]]) -> bool:
    if not references:
        return True
    return any(
        item.get("document_type") in (None, line.document_type)
        and item.get("document_number") in (None, line.document_number)
        for item in references
    )


def _missing_reference_numbers(
    references: list[dict[str, Any]],
    lines: list[RetrievedLine],
) -> list[str]:
    missing: list[str] = []
    for item in references:
        number = item.get("document_number")
        if not isinstance(number, str) or number in missing:
            continue
        document_type = item.get("document_type")
        if any(
            line.document_number == number
            and line.description
            and (document_type in (None, line.document_type))
            for line in lines
        ):
            continue
        missing.append(number)
    return missing


def _product_matches(line: RetrievedLine, product_code: str | None) -> bool:
    if product_code is None:
        return True
    return line.product_code == product_code


def _case_owner(result: dict[str, Any]) -> str | None:
    arguments = result.get("arguments")
    data = result.get("data")
    argument_case = arguments.get("case_id") if isinstance(arguments, dict) else None
    data_case = data.get("case_id") if isinstance(data, dict) else None
    if argument_case is not None and data_case is not None and str(argument_case) != str(data_case):
        return None
    owner = data_case if data_case is not None else argument_case
    if owner is None:
        return None
    return str(owner)


def _run_owner(result: dict[str, Any]) -> str | None:
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    run_id = data.get("run_id") or data.get("reconciliation_run_id")
    if run_id is None:
        return None
    return str(run_id)


def _credit_is_conditional(text: str) -> bool:
    lowered = text.lower()
    if "never be delivered" in lowered:
        return False
    return any(marker in lowered for marker in _CONDITIONAL_MARKERS)


def _uncertainty_is_explicit(action: str, text: str) -> bool:
    if action not in {
        "escalate_product_identity",
        "inconclusive",
        "request_supplier_clarification",
    }:
        return False
    lowered = text.lower()
    phrases = (
        "not established",
        "cannot establish",
        "could not establish",
        "unresolved",
        "do not establish",
        "does not establish",
        "equivalence",
        "identity",
    )
    return any(phrase in lowered for phrase in phrases)


def _recommendation_text(draft: RecommendationDraft) -> str:
    parts = [
        draft.summary,
        *draft.unresolved,
        *draft.observed_facts,
        *draft.possible_explanations,
        *draft.missing_evidence,
        *draft.next_actions,
    ]
    return "\n".join(parts)


def _gap(
    category: str,
    detail: str,
    *,
    product_code: str | None = None,
    document_numbers: list[str] | None = None,
) -> EvidenceGap:
    return EvidenceGap(
        category=category,
        detail=f"{category}: {detail}",
        product_code=product_code,
        document_numbers=list(document_numbers or []),
    )


def _unique(gaps: list[EvidenceGap]) -> list[EvidenceGap]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    unique: list[EvidenceGap] = []
    for gap in gaps:
        key = (gap.category, gap.detail, tuple(gap.document_numbers))
        if key in seen:
            continue
        seen.add(key)
        unique.append(gap)
    return unique


def _present(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
