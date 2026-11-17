"""Read-only investigation tools.

Each tool validates its arguments, refuses a case id other than the one bound
to the investigation, and returns a typed result. None of them writes a
procurement document, a reconciliation result, or a payment.
"""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.domain.decimals import format_decimal
from app.domain.investigation import TOOL_NAMES, CaseToolArgs, EvidenceItem, PolicyQueryArgs
from app.services.cases import get_case
from app.services.errors import NotFoundError
from app.services.policy_retrieval import PolicyRetriever, build_policy_retriever
from app.services.reconciliation import get_reconciliation

_INSTRUCTION = re.compile(
    r"ignore\s+(?:all\s+|any\s+|previous\s+|prior\s+)?instructions"
    r"|approve\s+(?:the\s+)?(?:invoice|payment)"
    r"|(?<!not )initiate\s+payment"
    r"|you\s+must\s+pay"
    r"|</?system>"
    r"|(?:^|\n)\s*system\s*:",
    re.IGNORECASE,
)
_SEARCH_LIMIT = 6


class ToolExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error_code: str | None = None
    error_detail: str | None = None
    found: bool | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    untrusted_instruction_detected: bool = False

    @property
    def evidence_labels(self) -> list[str]:
        return [item.label for item in self.evidence]

    def as_state(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["evidence_labels"] = self.evidence_labels
        return payload


class ToolExecutor:
    def __init__(
        self,
        session: Session,
        *,
        case_id: UUID,
        reconciliation_run_id: UUID,
        retriever: PolicyRetriever | None = None,
    ) -> None:
        self.session = session
        self.case_id = case_id
        self.reconciliation_run_id = reconciliation_run_id
        self.retriever = retriever or build_policy_retriever()

    def call(self, name: str, arguments: dict[str, Any]) -> ToolExecution:
        if name not in TOOL_NAMES:
            return _failure(name, arguments, "unknown_tool", "The tool is not available.")
        try:
            if name == "search_procurement_policy":
                query = PolicyQueryArgs.model_validate(arguments)
                return self._search(query)
            case_args = CaseToolArgs.model_validate(arguments)
        except ValidationError:
            return _failure(
                name,
                _safe_arguments(arguments),
                "invalid_arguments",
                "Tool arguments did not match the schema.",
            )
        if case_args.case_id != self.case_id:
            return _failure(
                name,
                {"case_id": str(case_args.case_id)},
                "case_access_denied",
                "The tool can only read the case bound to this investigation.",
            )
        if name == "get_procurement_case":
            return self._case(case_args.case_id)
        if name == "get_reconciliation_findings":
            return self._findings(case_args.case_id)
        if name == "get_purchase_order":
            return self._purchase_order(case_args.case_id)
        if name == "get_delivery_notes":
            return self._delivery_notes(case_args.case_id)
        if name == "get_invoices":
            return self._invoices(case_args.case_id)
        return _failure(name, arguments, "unknown_tool", "The tool is not available.")

    def _case(self, case_id: UUID) -> ToolExecution:
        try:
            case = get_case(self.session, case_id)
        except NotFoundError:
            return _missing("get_procurement_case", case_id, "procurement_case_missing")
        data = {
            "found": True,
            "content_trust": "untrusted",
            "reference": case.reference,
            "title": case.title,
            "summary": case.summary,
            "supplier_code": case.supplier.code,
            "supplier_name": case.supplier.name,
            "document_numbers": sorted(document.document_number for document in case.documents),
        }
        evidence = [
            EvidenceItem(
                tool_name="get_procurement_case",
                record_type="procurement_case",
                record_id=str(case.id),
                label=f"case:{case.reference}",
            )
        ]
        return _ok("get_procurement_case", case_id, data, evidence, scan=data)

    def _findings(self, case_id: UUID) -> ToolExecution:
        try:
            run = get_reconciliation(self.session, case_id, self.reconciliation_run_id)
        except NotFoundError:
            return _missing("get_reconciliation_findings", case_id, "reconciliation_missing")
        findings = []
        evidence: list[EvidenceItem] = []
        for finding in run.findings:
            product = finding.product_code or "none"
            label = f"finding:{finding.code}:{product}"
            sources: list[str] = []
            for reference in finding.source_references:
                number = reference.get("document_number")
                if isinstance(number, str) and number not in sources:
                    sources.append(number)
            findings.append(
                {
                    "code": finding.code,
                    "status": finding.status,
                    "product_code": finding.product_code,
                    "message": finding.message,
                    "unit": finding.unit,
                    "currency": finding.currency,
                    "ordered_quantity": _decimal(finding.ordered_quantity),
                    "delivered_quantity": _decimal(finding.delivered_quantity),
                    "invoiced_quantity": _decimal(finding.invoiced_quantity),
                    "quantity_difference": _decimal(finding.quantity_difference),
                    "purchase_order_unit_price": _decimal(finding.purchase_order_unit_price),
                    "invoice_unit_price": _decimal(finding.invoice_unit_price),
                    "price_difference": _decimal(finding.price_difference),
                    "sources": sources,
                    "source_references": [
                        {
                            "document_type": reference.get("document_type"),
                            "document_number": reference.get("document_number"),
                            "line_number": reference.get("line_number"),
                        }
                        for reference in finding.source_references
                        if isinstance(reference, dict)
                    ],
                    "content_trust": "untrusted",
                }
            )
            evidence.append(
                EvidenceItem(
                    tool_name="get_reconciliation_findings",
                    record_type="reconciliation_finding",
                    record_id=str(finding.id),
                    label=label,
                )
            )
        data = {
            "found": True,
            "case_id": str(case_id),
            "run_id": str(run.id),
            "run_status": run.status,
            "findings": findings,
            "content_trust": "untrusted",
        }
        return _ok("get_reconciliation_findings", case_id, data, evidence, scan=data)

    def _purchase_order(self, case_id: UUID) -> ToolExecution:
        case = get_case(self.session, case_id)
        order = case.purchase_order
        if order is None:
            return _missing("get_purchase_order", case_id, "purchase_order_missing")
        lines = [_line(line, priced=True) for line in order.lines]
        data = {
            "found": True,
            "case_id": str(case_id),
            "content_trust": "untrusted",
            "purchase_order": {
                "id": str(order.id),
                "number": order.number,
                "currency": order.currency,
                "issued_on": order.issued_on.isoformat(),
                "source_document_id": str(order.source_document_id),
                "lines": lines,
            },
        }
        evidence = [
            EvidenceItem(
                tool_name="get_purchase_order",
                record_type="purchase_order",
                record_id=str(order.id),
                label=f"purchase_order:{order.number}",
            ),
            *[
                EvidenceItem(
                    tool_name="get_purchase_order",
                    record_type="purchase_order_line",
                    record_id=str(line.id),
                    label=(
                        f"purchase_order_line:{order.number}:{line.line_number}:"
                        f"{line.product_code or 'none'}"
                    ),
                )
                for line in order.lines
            ],
        ]
        return _ok("get_purchase_order", case_id, data, evidence, scan=data)

    def _delivery_notes(self, case_id: UUID) -> ToolExecution:
        case = get_case(self.session, case_id)
        notes = sorted(case.delivery_notes, key=lambda item: item.number)
        if not notes:
            return _missing("get_delivery_notes", case_id, "delivery_notes_missing")
        payload = []
        evidence = []
        for note in notes:
            payload.append(
                {
                    "id": str(note.id),
                    "number": note.number,
                    "purchase_order_number": note.purchase_order_number,
                    "delivered_on": note.delivered_on.isoformat(),
                    "source_document_id": str(note.source_document_id),
                    "lines": [_line(line, priced=False) for line in note.lines],
                }
            )
            evidence.append(
                EvidenceItem(
                    tool_name="get_delivery_notes",
                    record_type="delivery_note",
                    record_id=str(note.id),
                    label=f"delivery_note:{note.number}",
                )
            )
            evidence.extend(
                EvidenceItem(
                    tool_name="get_delivery_notes",
                    record_type="delivery_note_line",
                    record_id=str(line.id),
                    label=(
                        f"delivery_note_line:{note.number}:{line.line_number}:"
                        f"{line.product_code or 'none'}"
                    ),
                )
                for line in note.lines
            )
        data = {
            "found": True,
            "case_id": str(case_id),
            "content_trust": "untrusted",
            "delivery_notes": payload,
        }
        return _ok("get_delivery_notes", case_id, data, evidence, scan=data)

    def _invoices(self, case_id: UUID) -> ToolExecution:
        case = get_case(self.session, case_id)
        invoices = sorted(case.invoices, key=lambda item: item.number)
        if not invoices:
            return _missing("get_invoices", case_id, "invoices_missing")
        payload = []
        evidence = []
        for invoice in invoices:
            payload.append(
                {
                    "id": str(invoice.id),
                    "number": invoice.number,
                    "purchase_order_number": invoice.purchase_order_number,
                    "currency": invoice.currency,
                    "issued_on": invoice.issued_on.isoformat(),
                    "source_document_id": str(invoice.source_document_id),
                    "lines": [_line(line, priced=True) for line in invoice.lines],
                }
            )
            evidence.append(
                EvidenceItem(
                    tool_name="get_invoices",
                    record_type="invoice",
                    record_id=str(invoice.id),
                    label=f"invoice:{invoice.number}",
                )
            )
            evidence.extend(
                EvidenceItem(
                    tool_name="get_invoices",
                    record_type="invoice_line",
                    record_id=str(line.id),
                    label=(
                        f"invoice_line:{invoice.number}:{line.line_number}:"
                        f"{line.product_code or 'none'}"
                    ),
                )
                for line in invoice.lines
            )
        data = {
            "found": True,
            "case_id": str(case_id),
            "content_trust": "untrusted",
            "invoices": payload,
        }
        return _ok("get_invoices", case_id, data, evidence, scan=data)

    def _search(self, query: PolicyQueryArgs) -> ToolExecution:
        hits = self.retriever.search(self.session, query.query, limit=_SEARCH_LIMIT)
        sections = [hit.as_dict() for hit in hits]
        evidence = [
            EvidenceItem(
                tool_name="search_procurement_policy",
                record_type="policy_section",
                record_id=section["section_id"],
                label=f"policy:{section['section_code']}",
            )
            for section in sections
        ]
        data = {
            "found": bool(sections),
            "retrieval": self.retriever.kind,
            "semantic_retrieval": False,
            "query": query.query,
            "sections": sections,
            "content_trust": "untrusted",
        }
        flagged = instruction_like(sections)
        return ToolExecution(
            tool_name="search_procurement_policy",
            arguments={"query": query.query},
            ok=True,
            found=bool(sections),
            data=data,
            evidence=evidence,
            untrusted_instruction_detected=flagged,
        )


def instruction_like(value: object) -> bool:
    if isinstance(value, str):
        return _INSTRUCTION.search(value) is not None
    if isinstance(value, dict):
        return any(instruction_like(item) for item in value.values())
    if isinstance(value, list):
        return any(instruction_like(item) for item in value)
    return False


def _ok(
    name: str,
    case_id: UUID,
    data: dict[str, Any],
    evidence: list[EvidenceItem],
    *,
    scan: object,
) -> ToolExecution:
    return ToolExecution(
        tool_name=name,
        arguments={"case_id": str(case_id)},
        ok=True,
        found=True,
        data=data,
        evidence=evidence,
        untrusted_instruction_detected=instruction_like(scan),
    )


def _missing(name: str, case_id: UUID, reason: str) -> ToolExecution:
    return ToolExecution(
        tool_name=name,
        arguments={"case_id": str(case_id)},
        ok=True,
        found=False,
        data={"found": False, "reason": reason, "content_trust": "untrusted"},
    )


def _failure(name: str, arguments: dict[str, Any], code: str, detail: str) -> ToolExecution:
    return ToolExecution(
        tool_name=name,
        arguments=arguments,
        ok=False,
        error_code=code,
        error_detail=detail,
        found=False,
    )


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    from decimal import Decimal

    if isinstance(value, Decimal):
        return format_decimal(value)
    return str(value)


def _line(line: object, *, priced: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "line_number": line.line_number,
        "product_code": line.product_code,
        "description": line.description,
        "quantity": format_decimal(line.quantity),
        "unit": line.unit,
        "content_trust": "untrusted",
    }
    if priced:
        payload["unit_price"] = format_decimal(line.unit_price)
        payload["currency"] = line.currency
    return payload
