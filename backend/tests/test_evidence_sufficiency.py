"""Evidence-gate tests. The model is a script. No provider is called."""

from uuid import uuid4

from tests.test_investigation import (
    _CASE_ID,
    _RUN_ID,
    ScriptedModel,
    _execution,
    _run,
)

from app.domain.investigation import (
    AgentDecision,
    DecisionAction,
    RecommendedAction,
    StructuredFindingDraft,
    ToolCall,
)
from app.services.investigation_tools import ToolExecution

_OTHER_CASE = "00000000-0000-4000-8000-000000000099"
_CREDIT = (
    "Observed facts: ordered 100, delivered 80, invoiced 100, difference 20. "
    "Possible explanation: the remaining quantity may still be delivered. "
    "Recommended next action: request a quantity credit only if the supplier "
    "confirms the remaining quantity will not be delivered. "
    "No invoice was approved and no payment was initiated."
)


def _line(
    number: str,
    *,
    product: str = "CEM-II-25",
    quantity: str = "80",
    price: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "line_number": 1,
        "product_code": product,
        "description": "Portland Cement CEM II 25kg",
        "quantity": quantity,
        "unit": "BAG",
    }
    if price is not None:
        payload["unit_price"] = price
        payload["currency"] = "EUR"
    return {"number": number, "lines": [payload]}


def _finding(
    code: str = "INVOICED_WITHOUT_DELIVERY",
    *,
    product: str = "CEM-II-25",
    references: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if references is None:
        references = [
            {"document_type": "purchase_order", "document_number": "PO-B-100", "line_number": 1},
            {"document_type": "delivery_note", "document_number": "DN-B-100", "line_number": 1},
            {"document_type": "invoice", "document_number": "INV-B-100", "line_number": 1},
        ]
    return {
        "found": True,
        "case_id": str(_CASE_ID),
        "run_id": str(_RUN_ID),
        "run_status": "EXCEPTION",
        "findings": [
            {
                "code": code,
                "status": "EXCEPTION",
                "product_code": product,
                "message": "Stored matcher finding.",
                "unit": "BAG",
                "currency": "EUR",
                "ordered_quantity": "100",
                "delivered_quantity": "80",
                "invoiced_quantity": "100",
                "quantity_difference": "20",
                "purchase_order_unit_price": "12.5",
                "invoice_unit_price": "13.75",
                "price_difference": "1.25",
                "sources": ["PO-B-100", "DN-B-100", "INV-B-100"],
                "source_references": references,
            }
        ],
    }


def _sections(*codes: str) -> list[dict[str, str]]:
    return [
        {
            "section_id": str(uuid4()),
            "document_code": code,
            "section_code": code,
            "version": "1.0",
            "heading": code,
            "excerpt": f"Synthetic policy {code}.",
            "content_trust": "untrusted",
        }
        for code in codes
    ]


def _tools(finding: dict[str, object], **documents: ToolExecution) -> object:
    from tests.test_investigation import MapTools

    sections = documents.pop("sections", None)
    policy_sections = (
        sections if isinstance(sections, list) else _sections("POL-QTY-001", "POL-APR-001")
    )
    base: dict[str, ToolExecution] = {
        "get_reconciliation_findings": _execution(
            "get_reconciliation_findings",
            data=finding,
            labels=[("finding:sample", "reconciliation_finding", str(uuid4()))],
        ),
        "search_procurement_policy": _execution(
            "search_procurement_policy",
            data={"found": True, "sections": policy_sections},
            labels=[
                (f"policy:{section['section_code']}", "policy_section", section["section_id"])
                for section in policy_sections
            ],
            arguments={"query": "policy"},
        ),
    }
    base.update(documents)
    return MapTools(base)


def _po(product: str = "CEM-II-25", *, case_id: str | None = None) -> ToolExecution:
    return _execution(
        "get_purchase_order",
        data={
            "found": True,
            "case_id": case_id or str(_CASE_ID),
            "purchase_order": _line("PO-B-100", product=product, quantity="100", price="12.5"),
        },
        labels=[("purchase_order:PO-B-100", "purchase_order", str(uuid4()))],
        arguments={"case_id": case_id or str(_CASE_ID)},
    )


def _delivery(*numbers: str, product: str = "CEM-II-25") -> ToolExecution:
    notes = [
        _line(number, product=product, quantity="40" if len(numbers) > 1 else "80")
        for number in numbers
    ]
    return _execution(
        "get_delivery_notes",
        data={"found": True, "case_id": str(_CASE_ID), "delivery_notes": notes},
        labels=[(f"delivery_note:{number}", "delivery_note", str(uuid4())) for number in numbers],
    )


def _invoice(product: str = "CEM-II-25") -> ToolExecution:
    return _execution(
        "get_invoices",
        data={
            "found": True,
            "case_id": str(_CASE_ID),
            "invoices": [_line("INV-B-100", product=product, quantity="100", price="13.75")],
        },
        labels=[("invoice:INV-B-100", "invoice", str(uuid4()))],
    )


def _recommend(
    action: RecommendedAction = RecommendedAction.REQUEST_QUANTITY_CREDIT, **extra: object
):
    summary = str(extra.pop("summary", _CREDIT))
    citations = list(extra.pop("citations", ["POL-QTY-001"]))
    unresolved = list(extra.pop("unresolved", []))
    prerequisites = extra.pop("prerequisites", None)
    decision_action = extra.pop("decision_action", None)
    if not isinstance(decision_action, DecisionAction):
        decision_action = (
            DecisionAction.INCONCLUSIVE
            if action is RecommendedAction.INCONCLUSIVE
            else DecisionAction.RECOMMEND
        )
    return AgentDecision(
        action=decision_action,
        decision_code="scripted_outcome",
        recommendation={
            "action": action,
            "summary": summary,
            "review_required": True,
            "finding_summaries": [
                StructuredFindingDraft(
                    code="scripted",
                    summary=summary,
                    evidence_labels=["finding:sample"],
                )
            ]
            if action is not RecommendedAction.INCONCLUSIVE
            else [],
            "citation_section_codes": citations,
            "evidence_labels": ["finding:sample"],
            "unresolved": unresolved or ["The script recorded an open question."],
            "prerequisites": (
                [{"kind": "future_delivery", "status": "unconfirmed"}]
                if action is RecommendedAction.REQUEST_QUANTITY_CREDIT and prerequisites is None
                else list(prerequisites or [])
            ),
        },
    )


def _call(*names: str) -> AgentDecision:
    return AgentDecision(
        action=DecisionAction.CALL_TOOLS,
        decision_code="scripted_tools",
        tool_calls=[
            ToolCall(
                name=name,
                arguments={"query": "quantity price policy"}
                if name == "search_procurement_policy"
                else {"case_id": str(_CASE_ID)},
            )
            for name in names
        ],
    )


def test_premature_credit_is_rejected_and_recovered_by_later_tool_calls() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _run(
        tools,
        model=ScriptedModel(
            [
                _call("search_procurement_policy"),
                _recommend(),
                _call("get_purchase_order", "get_delivery_notes", "get_invoices"),
                _recommend(),
            ]
        ),
    )

    assert result.status == "completed"
    assert result.evidence_validated is True
    assert result.recommended_action == "request_quantity_credit"
    assert any(event["event_type"] == "evidence_rejected" for event in result.events)
    names = [name for name, _arguments in tools.calls]
    assert names.index("search_procurement_policy") < names.index("get_purchase_order")
    assert "get_delivery_notes" in names
    assert "get_invoices" in names


def test_budget_exhaustion_is_inconclusive_and_names_the_missing_lines() -> None:
    tools = _tools(_finding())
    result = _run(
        tools,
        model=ScriptedModel([_call("search_procurement_policy"), _recommend()]),
        max_iterations=2,
    )

    assert result.status == "inconclusive"
    assert result.evidence_validated is False
    assert result.recommended_action == "inconclusive"
    assert "purchase_order_line" in (result.summary or "")
    assert "delivery_note_line" in (result.summary or "")
    assert "invoice_line" in (result.summary or "")


def test_missing_purchase_order_line_blocks_a_completed_credit() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _execution(
                "get_purchase_order",
                data={
                    "found": True,
                    "case_id": str(_CASE_ID),
                    "purchase_order": {"number": "PO-B-100"},
                },
                labels=[("purchase_order:PO-B-100", "purchase_order", str(uuid4()))],
            ),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _finish_without_recovery(tools)

    assert result.status == "inconclusive"
    assert result.evidence_validated is False
    assert "purchase_order_line" in " ".join(result.missing_evidence)


def test_missing_delivery_notes_are_named() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _execution(
                "get_delivery_notes",
                data={"found": False, "case_id": str(_CASE_ID), "reason": "delivery_notes_missing"},
                labels=[],
                found=False,
            ),
            "get_invoices": _invoice(),
        },
    )
    result = _finish_without_recovery(tools)

    assert result.status == "inconclusive"
    assert "delivery_note_line" in " ".join(result.missing_evidence)
    assert "get_delivery_notes" in " ".join(result.missing_evidence)


def test_multiple_partial_deliveries_all_need_line_records() -> None:
    finding = _finding(
        references=[
            {"document_type": "purchase_order", "document_number": "PO-B-100", "line_number": 1},
            {"document_type": "delivery_note", "document_number": "DN-D-080", "line_number": 1},
            {"document_type": "delivery_note", "document_number": "DN-D-020", "line_number": 1},
            {"document_type": "invoice", "document_number": "INV-B-100", "line_number": 1},
        ]
    )
    tools = _tools(
        finding,
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-D-080"),
            "get_invoices": _invoice(),
        },
    )
    result = _finish_without_recovery(tools)

    assert result.status == "inconclusive"
    assert "DN-D-020" in " ".join(result.missing_evidence)
    assert "DN-D-080" not in " ".join(result.missing_evidence)


def test_missing_invoice_line_is_not_replaced_by_a_header() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _execution(
                "get_invoices",
                data={
                    "found": True,
                    "case_id": str(_CASE_ID),
                    "invoices": [{"number": "INV-B-100"}],
                },
                labels=[("invoice:INV-B-100", "invoice", str(uuid4()))],
            ),
        },
    )
    result = _finish_without_recovery(tools)

    assert "invoice_line" in " ".join(result.missing_evidence)


def test_unrelated_product_line_does_not_satisfy_the_finding() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po("OTHER-1"),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _finish_without_recovery(tools)

    assert result.evidence_validated is False
    assert "CEM-II-25" in " ".join(result.missing_evidence)


def test_wrong_case_lines_are_ignored() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po(case_id=_OTHER_CASE),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _finish_without_recovery(tools)

    assert result.evidence_validated is False
    assert "purchase_order_line" in " ".join(result.missing_evidence)


def test_quantity_policy_must_be_retrieved() -> None:
    tools = _tools(
        _finding(),
        sections=_sections("POL-PRICE-001"),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _run(
        tools,
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(citations=["POL-PRICE-001"]),
                _recommend(citations=["POL-PRICE-001"]),
            ]
        ),
    )

    assert result.status == "inconclusive"
    assert "POL-QTY-001" in " ".join(result.missing_evidence)


def test_price_discrepancy_does_not_require_delivery_notes() -> None:
    tools = _tools(
        _finding("PRICE_MISMATCH"),
        sections=_sections("POL-PRICE-001", "POL-APR-001"),
        **{"get_purchase_order": _po(), "get_invoices": _invoice()},
    )
    result = _run(
        tools,
        model=ScriptedModel(
            [
                _call("get_purchase_order", "get_invoices", "search_procurement_policy"),
                _recommend(
                    RecommendedAction.HOLD_FOR_PRICE_REVIEW,
                    summary=(
                        "Observed facts: purchase-order price 12.5, invoice price 13.75, "
                        "difference 1.25. Recommended next action: hold the invoice for price "
                        "review. No invoice was approved and no payment was initiated."
                    ),
                    citations=["POL-PRICE-001"],
                ),
            ]
        ),
    )

    assert result.status == "completed"
    assert result.evidence_validated is True
    assert result.recommended_action == "hold_for_price_review"
    assert "get_delivery_notes" not in [name for name, _arguments in tools.calls]


def test_unconditional_credit_is_rejected_after_the_lines_are_present() -> None:
    tools = _tools(
        _finding(),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )
    result = _run(
        tools,
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(
                    summary=(
                        "The remaining 20 units will never be delivered. Request a credit. "
                        "No invoice was approved and no payment was initiated."
                    ),
                    prerequisites=[],
                ),
                _recommend(
                    summary=(
                        "The remaining 20 units will never be delivered. Request a credit. "
                        "No invoice was approved and no payment was initiated."
                    ),
                    prerequisites=[],
                ),
            ]
        ),
    )

    assert result.evidence_validated is False
    assert result.recommended_action == "inconclusive"
    assert "conditional" in " ".join(result.missing_evidence).lower()


def test_conditional_wording_without_the_prerequisite_is_rejected() -> None:
    result = _run(
        _complete_quantity_tools(),
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(summary=_CREDIT, prerequisites=[]),
                _recommend(summary=_CREDIT, prerequisites=[]),
            ]
        ),
    )

    assert result.evidence_validated is False
    assert result.recommended_action == "inconclusive"
    assert "future-delivery prerequisite" in " ".join(result.missing_evidence)


def test_structured_prerequisite_accepts_a_credit_without_marker_phrases() -> None:
    result = _run(
        _complete_quantity_tools(),
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(
                    summary=(
                        "Ordered 100, delivered 80, invoiced 100, difference 20. "
                        "Request a quantity credit. "
                        "No invoice was approved and no payment was initiated."
                    ),
                    prerequisites=[{"kind": "future_delivery", "status": "unconfirmed"}],
                ),
            ]
        ),
    )

    assert result.status == "completed"
    assert result.evidence_validated is True
    assert result.recommended_action == "request_quantity_credit"
    assert result.prerequisites == [{"kind": "future_delivery", "status": "unconfirmed"}]
    assert "only if the supplier" not in (result.summary or "")


def _complete_quantity_tools():
    return _tools(
        _finding(),
        **{
            "get_purchase_order": _po(),
            "get_delivery_notes": _delivery("DN-B-100"),
            "get_invoices": _invoice(),
        },
    )


def test_ambiguous_product_requires_explicit_uncertainty() -> None:
    references = [
        {"document_type": "purchase_order", "document_number": "PO-C-100", "line_number": 1},
        {"document_type": "delivery_note", "document_number": "DN-C-100", "line_number": 1},
        {"document_type": "invoice", "document_number": "INV-C-100", "line_number": 1},
    ]
    finding = _finding("UNCERTAIN_PRODUCT_MAPPING", product="CEM-II-25", references=references)
    finding["findings"][0]["product_code"] = None
    tools = _tools(
        finding,
        sections=_sections("POL-PROD-001"),
        **{
            "get_purchase_order": _execution(
                "get_purchase_order",
                data={
                    "found": True,
                    "case_id": str(_CASE_ID),
                    "purchase_order": {
                        "number": "PO-C-100",
                        "lines": [
                            {
                                "line_number": 1,
                                "product_code": None,
                                "description": "Portland Cement CEM II 25kg",
                                "quantity": "100",
                                "unit": "BAG",
                                "unit_price": "4.5",
                            }
                        ],
                    },
                },
                labels=[],
            ),
            "get_delivery_notes": _execution(
                "get_delivery_notes",
                data={
                    "found": True,
                    "case_id": str(_CASE_ID),
                    "delivery_notes": [
                        {
                            "number": "DN-C-100",
                            "lines": [
                                {
                                    "line_number": 1,
                                    "product_code": None,
                                    "description": "Cement bags 25 kg",
                                    "quantity": "100",
                                    "unit": "BAG",
                                }
                            ],
                        }
                    ],
                },
                labels=[],
            ),
            "get_invoices": _execution(
                "get_invoices",
                data={
                    "found": True,
                    "case_id": str(_CASE_ID),
                    "invoices": [
                        {
                            "number": "INV-C-100",
                            "lines": [
                                {
                                    "line_number": 1,
                                    "product_code": None,
                                    "description": "CEM II/A-LL 25KG",
                                    "quantity": "100",
                                    "unit": "BAG",
                                    "unit_price": "4.5",
                                }
                            ],
                        }
                    ],
                },
                labels=[],
            ),
        },
    )
    result = _run(
        tools,
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(
                    RecommendedAction.ESCALATE_PRODUCT_IDENTITY,
                    decision_action=DecisionAction.INCONCLUSIVE,
                    summary=(
                        "Equivalence could not be established from the retrieved descriptions. "
                        "The investigation is inconclusive. No invoice was approved and no "
                        "payment was initiated."
                    ),
                    citations=["POL-PROD-001"],
                    unresolved=["Product identity is unresolved."],
                ),
            ]
        ),
    )

    assert result.status == "inconclusive"
    assert result.evidence_validated is True
    assert result.recommended_action == "escalate_product_identity"


def _finish_without_recovery(tools: object):
    return _run(
        tools,
        model=ScriptedModel(
            [
                _call(
                    "get_purchase_order",
                    "get_delivery_notes",
                    "get_invoices",
                    "search_procurement_policy",
                ),
                _recommend(),
                _recommend(),
            ]
        ),
        **{},
    )
