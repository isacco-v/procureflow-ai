"""Deterministic investigation decisions.

This is a scripted test double. It looks at tool results and chooses the next
read-only tool, or a structured recommendation. It does not call a language
model, and a different observation can select a different tool. Document text
cannot change the tool arguments or the recommended action.
"""

from typing import Any

from app.domain.investigation import (
    AgentDecision,
    DecisionAction,
    DecisionObservation,
    ReasoningKind,
    RecommendationDraft,
    RecommendedAction,
    StructuredFindingDraft,
    ToolCall,
    ToolObservation,
)

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
_DOCUMENT_TOOLS = (
    "get_procurement_case",
    "get_purchase_order",
    "get_delivery_notes",
    "get_invoices",
)
_QUANTITY_QUERY = (
    "quantity discrepancy undelivered partial delivery invoice approval supplier clarification"
)
_PRICE_QUERY = "price discrepancy unit price invoice approval supplier clarification"
_PRODUCT_QUERY = "ambiguous product identifier description invoice approval supplier clarification"
_GENERIC_QUERY = "invoice approval supplier clarification discrepancy"
_CLOSING = "No invoice was approved and no payment was initiated."
_IGNORED = " Instruction-like text in an untrusted document was ignored."


class MockInvestigationModel:
    """Scripted tool selection. Not autonomous model reasoning."""

    name = "mock"
    model_name = "deterministic-investigation-double"
    reasoning_kind = ReasoningKind.DETERMINISTIC_TEST_DOUBLE.value

    def decide(self, observation: DecisionObservation) -> AgentDecision:
        failed = next((tool for tool in observation.tools if not tool.ok), None)
        if failed is not None:
            code = failed.error_code or "tool_failed"
            return _terminal(
                observation,
                decision_action=DecisionAction.INCONCLUSIVE,
                decision_code="required_tool_failed",
                action=RecommendedAction.INCONCLUSIVE,
                summary=(
                    f"Tool {failed.tool_name} failed ({code}). The investigation stopped "
                    f"without a financial recommendation. {_CLOSING}"
                ),
                unresolved=[f"{failed.tool_name} failed."],
            )

        findings = _findings(observation)
        if not findings:
            return _terminal(
                observation,
                decision_action=DecisionAction.INCONCLUSIVE,
                decision_code="no_actionable_exception",
                action=RecommendedAction.INCONCLUSIVE,
                summary=(
                    "The reconciliation findings were not available, so there is nothing "
                    f"to recommend. {_CLOSING}"
                ),
                unresolved=["Reconciliation findings were not available."],
            )

        codes = {str(row.get("code")) for row in findings if row.get("code")}
        if codes & _PRODUCT:
            return self._product(observation, findings)
        if codes & _QUANTITY:
            return self._quantity(observation, findings)
        if codes & _PRICE:
            return self._price(observation, findings)
        if codes <= {"LINE_RECONCILED"}:
            return _terminal(
                observation,
                decision_action=DecisionAction.INCONCLUSIVE,
                decision_code="no_actionable_exception",
                action=RecommendedAction.INCONCLUSIVE,
                summary=(
                    "The matcher did not report an exception that this investigation "
                    f"can explain. {_CLOSING}"
                ),
                unresolved=["No exception finding was present."],
            )
        return self._generic(observation, findings)

    def _quantity(
        self, observation: DecisionObservation, findings: list[dict[str, Any]]
    ) -> AgentDecision:
        missing = _missing_documents(observation)
        if missing:
            return _call(observation, "select_quantity_documents", missing)
        absent = _absent_documents(observation)
        if absent:
            return _terminal(
                observation,
                decision_action=DecisionAction.INCONCLUSIVE,
                decision_code="insufficient_evidence",
                action=RecommendedAction.INCONCLUSIVE,
                summary=(
                    "A quantity finding is present, but "
                    + " and ".join(absent)
                    + f" did not return a document. {_CLOSING}"
                ),
                unresolved=[f"{name} was not found." for name in absent],
            )
        if not _called(observation, "search_procurement_policy"):
            return _call(
                observation,
                "select_quantity_policy",
                ["search_procurement_policy"],
                query=_QUANTITY_QUERY,
            )
        cited = _cite(observation, ("POL-QTY-001", "POL-APR-001"), ("POL-DEL-001", "POL-SUP-001"))
        if cited is None:
            return _missing_policy(observation, "POL-QTY-001")
        finding = _preferred(findings, "INVOICED_WITHOUT_DELIVERY") or findings[0]
        product = _text(finding.get("product_code"), "unspecified product")
        unit = _text(finding.get("unit"), "")
        unit_suffix = f" {unit}" if unit else ""
        ordered = _text(finding.get("ordered_quantity"), "not recorded")
        delivered = _text(finding.get("delivered_quantity"), "not recorded")
        invoiced = _text(finding.get("invoiced_quantity"), "not recorded")
        difference = _text(finding.get("quantity_difference"), "not recorded")
        documents = _retrieved_numbers(observation)
        observed = (
            f"The matcher recorded product {product} as ordered {ordered}{unit_suffix}, "
            f"delivered {delivered}{unit_suffix}, invoiced {invoiced}{unit_suffix}, "
            f"difference {difference}. Retrieved documents: {documents}."
        )
        explanation = (
            "The remaining quantity may still be delivered. The retrieved delivery "
            "records do not show that the balance will never be delivered."
        )
        missing = "No retrieved document establishes that the remaining quantity is cancelled."
        action_text = (
            "Ask the supplier to clarify whether the balance will be delivered, and hold "
            "the invoice for human review. A quantity credit is appropriate only if the "
            "supplier confirms the remaining quantity will not be delivered."
        )
        summary = (
            f"Observed facts: {observed} Possible explanation: {explanation} "
            f"Missing evidence: {missing} Recommended next action: {action_text} {_CLOSING}"
        )
        labels = _evidence_for(observation, finding)
        return _terminal(
            observation,
            decision_action=DecisionAction.RECOMMEND,
            decision_code="request_supplier_clarification",
            action=RecommendedAction.REQUEST_SUPPLIER_CLARIFICATION,
            summary=summary,
            citations=cited,
            findings=[
                StructuredFindingDraft(
                    code="quantity_gap_observed",
                    summary=observed,
                    evidence_labels=labels,
                )
            ],
            evidence_labels=labels,
            observed_facts=[observed],
            possible_explanations=[explanation],
            missing_evidence=[missing],
            next_actions=[action_text],
        )

    def _price(
        self, observation: DecisionObservation, findings: list[dict[str, Any]]
    ) -> AgentDecision:
        missing = [
            name
            for name in ("get_procurement_case", "get_purchase_order", "get_invoices")
            if not _called(observation, name)
        ]
        if missing:
            return _call(observation, "select_price_documents", missing)
        absent = [
            name
            for name in ("get_purchase_order", "get_invoices")
            if _found(observation, name) is False
        ]
        if absent:
            return _terminal(
                observation,
                decision_action=DecisionAction.INCONCLUSIVE,
                decision_code="insufficient_evidence",
                action=RecommendedAction.INCONCLUSIVE,
                summary=(
                    "A price finding is present, but "
                    + " and ".join(absent)
                    + f" did not return a document. {_CLOSING}"
                ),
                unresolved=[f"{name} was not found." for name in absent],
            )
        if not _called(observation, "search_procurement_policy"):
            return _call(
                observation,
                "select_price_policy",
                ["search_procurement_policy"],
                query=_PRICE_QUERY,
            )
        cited = _cite(observation, ("POL-PRICE-001", "POL-APR-001"), ("POL-SUP-001",))
        if cited is None:
            return _missing_policy(observation, "POL-PRICE-001")
        finding = _preferred(findings, "PRICE_MISMATCH") or findings[0]
        product = _text(finding.get("product_code"), "unspecified product")
        currency = _text(finding.get("currency"), "")
        currency_suffix = f" {currency}" if currency else ""
        summary = (
            f"The matcher reported a price exception for product {product}. "
            "Purchase-order unit price "
            f"{_text(finding.get('purchase_order_unit_price'), 'not recorded')}{currency_suffix}, "
            "invoice unit price "
            f"{_text(finding.get('invoice_unit_price'), 'not recorded')}{currency_suffix}, "
            f"difference {_text(finding.get('price_difference'), 'not recorded')}. "
            f"Sources: {_sources(finding)}. "
            "Policy POL-PRICE-001 holds a unit-price difference for a person to review. "
            f"{_CLOSING}"
        )
        labels = _evidence_for(observation, finding)
        return _terminal(
            observation,
            decision_action=DecisionAction.RECOMMEND,
            decision_code="recommend_price_hold",
            action=RecommendedAction.HOLD_FOR_PRICE_REVIEW,
            summary=summary,
            citations=cited,
            findings=[
                StructuredFindingDraft(
                    code="price_gap_confirmed",
                    summary=summary,
                    evidence_labels=labels,
                )
            ],
            evidence_labels=labels,
        )

    def _product(
        self, observation: DecisionObservation, findings: list[dict[str, Any]]
    ) -> AgentDecision:
        missing = _missing_documents(observation)
        if missing:
            return _call(observation, "select_product_documents", missing)
        if not _called(observation, "search_procurement_policy"):
            return _call(
                observation,
                "select_product_policy",
                ["search_procurement_policy"],
                query=_PRODUCT_QUERY,
            )
        cited = _cite(observation, ("POL-PROD-001", "POL-APR-001"), ("POL-SUP-001",))
        if cited is None:
            return _missing_policy(observation, "POL-PROD-001")
        finding = findings[0]
        message = _text(finding.get("message"), "The matcher did not supply a message.")
        summary = (
            "The matcher could not establish product identity, so no financial comparison "
            f"was accepted. {message} Policy POL-PROD-001 says a description is not a "
            f"product identifier. The investigation is inconclusive. {_CLOSING}"
        )
        labels = _evidence_for(observation, finding)
        return _terminal(
            observation,
            decision_action=DecisionAction.INCONCLUSIVE,
            decision_code="escalate_product_identity",
            action=RecommendedAction.ESCALATE_PRODUCT_IDENTITY,
            summary=summary,
            citations=cited,
            findings=[
                StructuredFindingDraft(
                    code="product_identity_unresolved",
                    summary="The lines do not share a product code, so they were not matched.",
                    evidence_labels=labels,
                )
            ],
            evidence_labels=labels,
            unresolved=["Product identity is unresolved."],
        )

    def _generic(
        self, observation: DecisionObservation, findings: list[dict[str, Any]]
    ) -> AgentDecision:
        missing = _missing_documents(observation)
        if missing:
            return _call(observation, "select_clarification_documents", missing)
        if not _called(observation, "search_procurement_policy"):
            return _call(
                observation,
                "select_clarification_policy",
                ["search_procurement_policy"],
                query=_GENERIC_QUERY,
            )
        cited = _cite(observation, ("POL-SUP-001", "POL-APR-001"))
        if cited is None:
            return _missing_policy(observation, "POL-SUP-001")
        codes = ", ".join(str(row.get("code")) for row in findings if row.get("code"))
        summary = (
            f"The matcher reported {codes}. The investigation does not have a more specific "
            "rule for this combination, so a person should ask the supplier to clarify "
            f"using policy POL-SUP-001. {_CLOSING}"
        )
        labels = _evidence_for(observation, findings[0])
        return _terminal(
            observation,
            decision_action=DecisionAction.RECOMMEND,
            decision_code="request_supplier_clarification",
            action=RecommendedAction.REQUEST_SUPPLIER_CLARIFICATION,
            summary=summary,
            citations=cited,
            findings=[
                StructuredFindingDraft(
                    code="clarification_required",
                    summary=summary,
                    evidence_labels=labels,
                )
            ],
            evidence_labels=labels,
        )


def _call(
    observation: DecisionObservation,
    decision_code: str,
    names: list[str],
    *,
    query: str | None = None,
) -> AgentDecision:
    calls: list[ToolCall] = []
    for name in names:
        if name == "search_procurement_policy":
            arguments: dict[str, Any] = {"query": query}
        else:
            arguments = {"case_id": observation.case_id}
        calls.append(ToolCall(name=name, arguments=arguments))
    return AgentDecision(
        action=DecisionAction.CALL_TOOLS,
        decision_code=decision_code,
        tool_calls=calls,
    )


def _terminal(
    observation: DecisionObservation,
    *,
    decision_action: DecisionAction,
    decision_code: str,
    action: RecommendedAction,
    summary: str,
    unresolved: list[str] | None = None,
    citations: list[str] | None = None,
    findings: list[StructuredFindingDraft] | None = None,
    evidence_labels: list[str] | None = None,
    observed_facts: list[str] | None = None,
    possible_explanations: list[str] | None = None,
    missing_evidence: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> AgentDecision:
    text = summary
    if observation.untrusted_instruction_detected and _IGNORED.strip() not in text:
        text = text + _IGNORED
    return AgentDecision(
        action=decision_action,
        decision_code=decision_code,
        recommendation=RecommendationDraft(
            action=action,
            summary=text,
            review_required=True,
            finding_summaries=findings or [],
            citation_section_codes=citations or [],
            evidence_labels=evidence_labels or [],
            unresolved=unresolved or [],
            observed_facts=observed_facts or [],
            possible_explanations=possible_explanations or [],
            missing_evidence=missing_evidence or [],
            next_actions=next_actions or [],
        ),
    )


def _missing_policy(observation: DecisionObservation, code: str) -> AgentDecision:
    return _terminal(
        observation,
        decision_action=DecisionAction.INCONCLUSIVE,
        decision_code="policy_not_retrieved",
        action=RecommendedAction.INCONCLUSIVE,
        summary=(
            f"The policy search did not return {code}, so the investigation will not "
            f"invent a rule. {_CLOSING}"
        ),
        unresolved=[f"{code} was not retrieved."],
    )


def _latest(observation: DecisionObservation, name: str) -> ToolObservation | None:
    found = None
    for tool in observation.tools:
        if tool.tool_name == name:
            found = tool
    return found


def _called(observation: DecisionObservation, name: str) -> bool:
    tool = _latest(observation, name)
    return tool is not None and tool.ok


def _found(observation: DecisionObservation, name: str) -> bool | None:
    tool = _latest(observation, name)
    if tool is None or not tool.ok:
        return None
    return tool.found


def _missing_documents(observation: DecisionObservation) -> list[str]:
    return [name for name in _DOCUMENT_TOOLS if not _called(observation, name)]


def _absent_documents(observation: DecisionObservation) -> list[str]:
    return [
        name
        for name in ("get_purchase_order", "get_delivery_notes", "get_invoices")
        if _found(observation, name) is False
    ]


def _findings(observation: DecisionObservation) -> list[dict[str, Any]]:
    tool = _latest(observation, "get_reconciliation_findings")
    if tool is None or not tool.ok:
        return []
    raw = tool.data.get("findings")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _preferred(findings: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    for row in findings:
        if row.get("code") == code:
            return row
    return None


def _sections(observation: DecisionObservation) -> set[str]:
    tool = _latest(observation, "search_procurement_policy")
    if tool is None or not tool.ok:
        return set()
    raw = tool.data.get("sections")
    if not isinstance(raw, list):
        return set()
    return {
        str(row["section_code"])
        for row in raw
        if isinstance(row, dict) and isinstance(row.get("section_code"), str)
    }


def _cite(
    observation: DecisionObservation,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> list[str] | None:
    present = _sections(observation)
    if not set(required) <= present:
        return None
    cited = list(required)
    for code in optional:
        if code in present and code not in cited:
            cited.append(code)
    return cited


def _labels(observation: DecisionObservation, prefix: str) -> list[str]:
    collected: list[str] = []
    for tool in observation.tools:
        if not tool.ok:
            continue
        for label in tool.evidence_labels:
            if label.startswith(prefix) and label not in collected:
                collected.append(label)
    return collected


def _evidence_for(observation: DecisionObservation, finding: dict[str, Any]) -> list[str]:
    product = finding.get("product_code") or "none"
    expected = f"finding:{finding.get('code')}:{product}"
    labels = [expected] if expected in _labels(observation, "finding:") else []
    for prefix in ("purchase_order:", "delivery_note:", "invoice:", "case:"):
        labels.extend(_labels(observation, prefix))
    return labels


def _retrieved_numbers(observation: DecisionObservation) -> str:
    numbers: list[str] = []
    for name, key in (
        ("get_purchase_order", "purchase_order"),
        ("get_delivery_notes", "delivery_notes"),
        ("get_invoices", "invoices"),
    ):
        tool = _latest(observation, name)
        if tool is None or not tool.ok or tool.found is False:
            continue
        if name == "get_purchase_order":
            document = tool.data.get(key)
            documents = [document] if isinstance(document, dict) else []
        else:
            raw = tool.data.get(key)
            documents = raw if isinstance(raw, list) else []
        for document in documents:
            if isinstance(document, dict) and isinstance(document.get("number"), str):
                numbers.append(document["number"])
    return ", ".join(numbers) if numbers else "none retrieved"


def _sources(finding: dict[str, Any]) -> str:
    raw = finding.get("sources")
    if isinstance(raw, list) and raw:
        return ", ".join(str(item) for item in raw)
    return "none recorded"


def _text(value: object, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return str(value)
