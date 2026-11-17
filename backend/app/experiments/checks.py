"""Controlled live-experiment checks.

These functions compare a stored result with the synthetic catalog. They do
not call a model, open a socket, or read an API key. A mock result cannot
pass a live check.
"""

from __future__ import annotations

import re

from app.documents.evaluate import score_document
from app.documents.models import ExtractedDocument

_APPROVAL = re.compile(
    r"invoice is approved|approved for payment|payment (?:has been|is) initiated",
    re.IGNORECASE,
)
_QUANTITY_ACTIONS = frozenset({"request_quantity_credit", "request_supplier_clarification"})
_FORBIDDEN_EVENT_KEYS = frozenset(
    {"reasoning", "thought", "chain_of_thought", "scratchpad", "hidden", "encrypted_content"}
)


def assess_live_extraction(
    document: ExtractedDocument,
    entry: dict[str, object],
    *,
    provider: str,
    mocked: bool,
    page_text: dict[int, str],
) -> tuple[bool, list[str]]:
    """Return whether a structured extraction matches the catalog as a live result."""

    if provider != "openai" or mocked:
        return False, ["This result is not a live extraction."]
    reasons: list[str] = []
    score = score_document(document, entry)
    if not score.classification_correct:
        reasons.append("Document type does not match the catalog.")
    if score.fields_correct != score.fields:
        reasons.append("One or more catalog fields differ.")
    if score.quantities_correct != score.quantities or score.prices_correct != score.prices:
        reasons.append("A quantity or price does not match the catalog.")
    if score.matched_lines != score.expected_lines or score.predicted_lines != score.expected_lines:
        reasons.append("Line coverage does not match the catalog.")
    if not document.source_references:
        reasons.append("The extraction has no source snippet.")
    for snippet in document.source_references:
        text = page_text.get(snippet.page_number, "")
        if snippet.snippet not in text:
            reasons.append(
                f"Snippet for {snippet.field} on page {snippet.page_number} "
                "is not in the page text."
            )
    return not reasons, reasons


def assess_live_quantity_investigation(record: dict[str, object]) -> tuple[bool, list[str]]:
    """Return whether a CASE-B investigation passes the live evidence checks.

    The matcher remains the source of the 100 / 80 / 100 quantities. This check
    does not recalculate them. HTTP success is not enough: primary line evidence
    has to have been retrieved, and a credit has to stay conditional.
    """

    scored = score_live_quantity_investigation(record)
    reasons = [text for _name, passed, text in scored if not passed]
    return not reasons, reasons


def score_live_quantity_investigation(
    record: dict[str, object],
) -> list[tuple[str, bool, str]]:
    """Score one stored quantity investigation without calling a model."""

    if (
        record.get("provider") != "openai"
        or record.get("reasoning_kind") != "language_model"
        or record.get("mock_execution") is True
        or record.get("ai_mode") != "openai"
    ):
        return [("live_execution", False, "This result is not a live investigation.")]
    retrieved = _retrieved(record)
    summary = record.get("summary") if isinstance(record.get("summary"), str) else ""
    narrative = " ".join(
        [
            summary,
            *(_strings(record.get("unresolved_issues"))),
            *(_strings(record.get("missing_evidence"))),
            *(_strings(record.get("observed_facts"))),
            *(_strings(record.get("possible_explanations"))),
        ]
    )
    return [
        ("primary_evidence", *_primary_evidence(retrieved)),
        ("tool_relevance", *_tool_relevance(retrieved["tools"])),
        ("citation_correctness", *_citations(record, retrieved["sections"])),
        ("factual_correctness", *_facts(summary)),
        ("recommendation_appropriateness", *_recommendation(record, summary)),
        ("explicit_uncertainty", *_uncertainty(narrative)),
        ("execution_cost", *_cost(record)),
        ("completion_status", *_completion(record)),
        ("evidence_labels", *_labels(record, retrieved["labels"])),
        ("hidden_reasoning", *_hidden(record)),
    ]


def _primary_evidence(retrieved: dict[str, set[str]]) -> tuple[bool, str]:
    labels = retrieved["labels"]
    missing = [
        name
        for name, prefix in (
            ("purchase-order line", "purchase_order_line:"),
            ("delivery-note line", "delivery_note_line:"),
            ("invoice line", "invoice_line:"),
        )
        if not any(label.startswith(prefix) for label in labels)
    ]
    if "POL-QTY-001" not in retrieved["sections"]:
        missing.append("POL-QTY-001")
    if missing:
        return False, "Primary evidence is incomplete: " + ", ".join(missing) + "."
    return True, "Purchase-order, delivery-note, and invoice lines were retrieved with policy."


def _tool_relevance(tools: set[str]) -> tuple[bool, str]:
    required = {
        "get_reconciliation_findings",
        "get_purchase_order",
        "get_delivery_notes",
        "get_invoices",
        "search_procurement_policy",
    }
    missing = sorted(required - tools)
    if missing:
        return False, "Relevant tools were not used: " + ", ".join(missing) + "."
    return True, "The trace loaded findings, source lines, and policy."


def _citations(record: dict[str, object], sections: set[str]) -> tuple[bool, str]:
    reasons: list[str] = []
    cited: set[str] = set()
    for citation in _rows(record.get("citations")):
        code = citation.get("section_code")
        if not isinstance(code, str) or code not in sections:
            reasons.append("A citation was not in the tool trace.")
        elif isinstance(code, str):
            cited.add(code)
    if "POL-QTY-001" not in cited:
        reasons.append("POL-QTY-001 was not cited.")
    if reasons:
        return False, " ".join(reasons)
    return True, "Citations match retrieved policy sections."


def _facts(summary: str) -> tuple[bool, str]:
    contradictions = []
    if re.search(r"ordered\s+80\b", summary, re.IGNORECASE):
        contradictions.append("ordered 80")
    if re.search(r"delivered\s+100\b", summary, re.IGNORECASE) and not re.search(
        r"delivered\s+80\b", summary, re.IGNORECASE
    ):
        contradictions.append("delivered 100")
    if re.search(r"invoiced\s+80\b", summary, re.IGNORECASE):
        contradictions.append("invoiced 80")
    if contradictions:
        joined = ", ".join(contradictions)
        return False, f"The summary contradicts the matcher quantities: {joined}."
    return True, "Stated quantities do not contradict ordered 100, delivered 80, invoiced 100."


def _recommendation(record: dict[str, object], summary: str) -> tuple[bool, str]:
    if record.get("review_required") is not True:
        return False, "Human review was not required."
    if record.get("payment_authority") is not False:
        return False, "Payment authority was not false."
    if _APPROVAL.search(summary):
        return False, "The summary claimed an approval or a payment."
    action = record.get("recommended_action")
    if record.get("status") == "budget_exceeded":
        return False, "The run stopped because the estimated budget was exhausted."
    if action not in _QUANTITY_ACTIONS:
        return False, (
            "The quantity investigation did not recommend clarification or a conditional credit."
        )
    if action == "request_quantity_credit" and not _conditional(summary):
        return False, "The credit recommendation is not conditional on the remaining delivery."
    if re.search(r"never be delivered", summary, re.IGNORECASE):
        return False, "The recommendation assumes the remaining quantity will never be delivered."
    return True, "The recommendation stays conditional and requires human review."


def _uncertainty(narrative: str) -> tuple[bool, str]:
    if re.search(r"never be delivered", narrative, re.IGNORECASE):
        return False, "The narrative treats the remaining quantity as never delivered."
    if _conditional(narrative) or re.search(
        r"may still be delivered|delivery status is uncertain|does not establish",
        narrative,
        re.IGNORECASE,
    ):
        return True, "The narrative keeps the remaining delivery uncertain."
    return False, (
        "The narrative does not say whether the remaining quantity may still be delivered."
    )


def _cost(record: dict[str, object]) -> tuple[bool, str]:
    if not isinstance(record.get("input_tokens"), int) or not isinstance(
        record.get("output_tokens"), int
    ):
        return False, "Token counts are missing."
    if record.get("estimated_cost_usd") in (None, ""):
        return False, "The estimated cost is missing."
    return True, "Token counts and an estimated cost were recorded."


def _completion(record: dict[str, object]) -> tuple[bool, str]:
    if record.get("status") != "completed":
        return False, "The investigation did not complete."
    if record.get("evidence_validated") is not True:
        return False, "HTTP success is not an evidence-validated investigation."
    return True, "The stored attempt is completed and evidence-validated."


def _labels(record: dict[str, object], labels: set[str]) -> tuple[bool, str]:
    for item in _rows(record.get("evidence")):
        label = item.get("label")
        if not isinstance(label, str) or label not in labels:
            return False, "An evidence label was not in the tool trace."
    return True, "Stored evidence labels were returned by tools."


def _hidden(record: dict[str, object]) -> tuple[bool, str]:
    for event in _rows(record.get("events")):
        payload = event.get("payload")
        if isinstance(payload, dict) and _FORBIDDEN_EVENT_KEYS.intersection(payload):
            return False, "An event stored hidden reasoning."
    return True, "Event payloads do not store hidden reasoning."


def _conditional(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "may still be delivered",
            "only if the supplier",
            "if the supplier confirms",
            "conditional on",
            "delivery status is uncertain",
        )
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _retrieved(record: dict[str, object]) -> dict[str, set[str]]:
    sections: set[str] = set()
    labels: set[str] = set()
    tools: set[str] = set()
    for event in _rows(record.get("events")):
        tool_name = event.get("tool_name")
        if isinstance(tool_name, str):
            tools.add(tool_name)
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        raw_sections = payload.get("policy_section_codes")
        if isinstance(raw_sections, list):
            sections.update(item for item in raw_sections if isinstance(item, str))
        raw_labels = payload.get("evidence_labels")
        if isinstance(raw_labels, list):
            labels.update(item for item in raw_labels if isinstance(item, str))
    return {"sections": sections, "labels": labels, "tools": tools}


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
