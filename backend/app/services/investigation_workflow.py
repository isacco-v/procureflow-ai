"""LangGraph investigation workflow.

The model-controlled step is tool selection. Loading the reconciliation
findings, enforcing budgets, validating the recommendation, and handing the
case to a person are ordinary code. Tracing to LangSmith is forced off so a
local key cannot send this run to an external service.
"""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_TRACING"] = "false"

import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from decimal import Decimal  # noqa: E402
from typing import Any, Protocol, TypedDict  # noqa: E402
from uuid import UUID  # noqa: E402

from langgraph.graph import END, START, StateGraph  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.ai.investigation import InvestigationModel  # noqa: E402
from app.ai.investigation_errors import InvestigationModelStop  # noqa: E402
from app.domain.investigation import (  # noqa: E402
    INVESTIGATION_CONSTRAINTS,
    AgentDecision,
    DecisionAction,
    DecisionObservation,
    EvidenceGap,
    InvestigationBudgets,
    InvestigationStatus,
    ReasoningKind,
    ToolObservation,
)
from app.services.evidence_sufficiency import assess_evidence  # noqa: E402
from app.services.investigation_tools import ToolExecution  # noqa: E402
from app.services.investigation_validation import (  # noqa: E402
    ValidationRejection,
    hydrate_recommendation,
)

_FORBIDDEN_EVENT_KEYS = frozenset(
    {"reasoning", "thought", "chain_of_thought", "scratchpad", "hidden"}
)


class Clock(Protocol):
    def monotonic(self) -> float: ...


class ToolCaller(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolExecution: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


class InvestigationState(TypedDict, total=False):
    case_id: str
    reconciliation_run_id: str
    ai_mode: str
    provider: str
    model_name: str
    reasoning_kind: str
    status: str
    next_node: str
    iteration: int
    tool_call_count: int
    deadline: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    tool_results: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    events: list[dict[str, Any]]
    draft: dict[str, Any] | None
    proposed_status: str | None
    findings: list[dict[str, Any]]
    unresolved: list[str]
    citations: list[dict[str, Any]]
    summary: str | None
    recommended_action: str | None
    review_required: bool
    observed_facts: list[str]
    possible_explanations: list[str]
    missing_evidence: list[str]
    next_actions: list[str]
    evidence_feedback: list[dict[str, Any]]
    evidence_validated: bool
    tool_count_at_rejection: int
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    recommended_action: str | None
    review_required: bool
    summary: str | None
    findings: list[dict[str, Any]]
    unresolved: list[str]
    citations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    events: list[dict[str, Any]]
    error_code: str | None
    error_detail: str | None
    observed_facts: list[str]
    possible_explanations: list[str]
    missing_evidence: list[str]
    next_actions: list[str]
    evidence_validated: bool
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    iteration_count: int
    tool_call_count: int
    provider: str
    model_name: str
    reasoning_kind: str
    ai_mode: str


def run_workflow(
    *,
    case_id: UUID,
    reconciliation_run_id: UUID,
    ai_mode: str,
    model: InvestigationModel,
    tools: ToolCaller,
    budgets: InvestigationBudgets,
    clock: Clock | None = None,
) -> WorkflowResult:
    timer = clock or SystemClock()
    graph = _compile(model=model, tools=tools, budgets=budgets, clock=timer)
    final = graph.invoke(
        _initial(
            case_id=case_id,
            reconciliation_run_id=reconciliation_run_id,
            ai_mode=ai_mode,
            model=model,
        ),
        config={"recursion_limit": budgets.max_iterations * 4 + 20},
    )
    return _result(final)


def _compile(
    *,
    model: InvestigationModel,
    tools: ToolCaller,
    budgets: InvestigationBudgets,
    clock: Clock,
):
    def initialize(state: InvestigationState) -> dict[str, Any]:
        now = clock.monotonic()
        events = _append(
            [],
            "investigation_started",
            "Investigation started for the bound reconciliation run.",
            {"ai_mode": state["ai_mode"], "reasoning_kind": state["reasoning_kind"]},
        )
        return {
            "deadline": now + budgets.timeout_seconds,
            "events": events,
            "next_node": "retrieve_context",
        }

    def retrieve_context(state: InvestigationState) -> dict[str, Any]:
        if _expired(state, clock):
            return _exhausted(
                state, InvestigationStatus.TIMED_OUT, "timeout", "The time limit was reached."
            )
        if state["tool_call_count"] >= budgets.max_tool_calls:
            return _exhausted(
                state,
                InvestigationStatus.STEP_LIMIT,
                "tool_call_limit",
                "The tool-call limit was reached.",
            )
        execution = _invoke_tool(
            tools,
            "get_reconciliation_findings",
            {"case_id": state["case_id"]},
        )
        events = _tool_event(state["events"], execution, initiator="workflow")
        return {
            "tool_results": [execution.as_state()],
            "tool_call_count": state["tool_call_count"] + 1,
            "evidence": _merge_evidence([], execution),
            "events": events,
            "next_node": "decide",
        }

    def decide(state: InvestigationState) -> dict[str, Any]:
        if _expired(state, clock):
            return _exhausted(
                state, InvestigationStatus.TIMED_OUT, "timeout", "The time limit was reached."
            )
        iteration = state["iteration"] + 1
        if iteration > budgets.max_iterations:
            return _exhausted(
                state,
                InvestigationStatus.STEP_LIMIT,
                "iteration_limit",
                "The iteration limit was reached.",
                iteration=iteration,
            )
        try:
            decision = model.decide(_observation(state, iteration, budgets, clock))
        except InvestigationModelStop as stop:
            return _stopped_model(state, budgets, iteration, stop)
        except ValidationError:
            events = _append(
                state["events"],
                "output_rejected",
                "The decision did not match the investigation schema.",
                {"error_code": "invalid_output"},
            )
            return {
                "iteration": iteration,
                "status": InvestigationStatus.INVALID_OUTPUT.value,
                "error_code": "invalid_output",
                "error_detail": "The decision did not match the investigation schema.",
                "summary": None,
                "recommended_action": None,
                "findings": [],
                "citations": [],
                "unresolved": ["The decision was rejected."],
                "events": events,
                "next_node": "handoff",
            }
        input_tokens = state["input_tokens"] + decision.input_tokens
        output_tokens = state["output_tokens"] + decision.output_tokens
        cost = Decimal(state["estimated_cost_usd"]) + decision.estimated_cost_usd
        events = _append(
            state["events"],
            "model_decision",
            _decision_summary(state["reasoning_kind"], decision),
            {
                "decision_code": decision.decision_code,
                "action": decision.action.value,
                "tool_names": [call.name for call in decision.tool_calls],
                "recommended_action": (
                    None
                    if decision.recommendation is None
                    else decision.recommendation.action.value
                ),
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "estimated_cost_usd": format(decision.estimated_cost_usd, "f"),
            },
        )
        updated = {
            "iteration": iteration,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": format(cost, "f"),
            "events": events,
            "evidence_feedback": [],
        }
        if cost > budgets.max_estimated_cost_usd:
            stopped = _exhausted(
                {**state, **updated},
                InvestigationStatus.BUDGET_EXCEEDED,
                "cost_limit",
                "The estimated-cost limit was reached.",
                iteration=iteration,
            )
            stopped["input_tokens"] = input_tokens
            stopped["output_tokens"] = output_tokens
            stopped["estimated_cost_usd"] = format(cost, "f")
            return stopped
        if decision.action is DecisionAction.CALL_TOOLS:
            if state["tool_call_count"] + len(decision.tool_calls) > budgets.max_tool_calls:
                return _exhausted(
                    {**state, **updated},
                    InvestigationStatus.STEP_LIMIT,
                    "tool_call_limit",
                    "The tool-call limit was reached.",
                    iteration=iteration,
                )
            return {
                **updated,
                "pending_tool_calls": [
                    call.model_dump(mode="json") for call in decision.tool_calls
                ],
                "next_node": "execute_tools",
            }
        return {
            **updated,
            "draft": None
            if decision.recommendation is None
            else decision.recommendation.model_dump(mode="json"),
            "proposed_status": (
                InvestigationStatus.INCONCLUSIVE.value
                if decision.action is DecisionAction.INCONCLUSIVE
                else InvestigationStatus.COMPLETED.value
            ),
            "next_node": "validate",
        }

    def execute_tools(state: InvestigationState) -> dict[str, Any]:
        if _expired(state, clock):
            return _exhausted(
                state, InvestigationStatus.TIMED_OUT, "timeout", "The time limit was reached."
            )
        results = list(state["tool_results"])
        evidence = list(state["evidence"])
        events = list(state["events"])
        count = state["tool_call_count"]
        for call in state["pending_tool_calls"]:
            execution = _invoke_tool(tools, str(call["name"]), dict(call.get("arguments") or {}))
            results.append(execution.as_state())
            evidence = _merge_evidence(evidence, execution)
            events = _tool_event(events, execution, initiator="model")
            count += 1
        return {
            "tool_results": results,
            "evidence": evidence,
            "events": events,
            "tool_call_count": count,
            "pending_tool_calls": [],
            "next_node": "decide",
        }

    def validate(state: InvestigationState) -> dict[str, Any]:
        try:
            hydrated = hydrate_recommendation(state.get("draft") or {}, state["tool_results"])
        except ValidationRejection as exc:
            events = _append(
                state["events"],
                "output_rejected",
                exc.reason,
                {"error_code": "invalid_output"},
            )
            return {
                "status": InvestigationStatus.INVALID_OUTPUT.value,
                "error_code": "invalid_output",
                "error_detail": exc.reason,
                "summary": None,
                "recommended_action": None,
                "findings": [],
                "citations": [],
                "unresolved": [exc.reason],
                "events": events,
                "next_node": "handoff",
            }
        assessment = assess_evidence(
            case_id=state["case_id"],
            reconciliation_run_id=state["reconciliation_run_id"],
            tool_results=list(state["tool_results"]),
            recommendation=state.get("draft") or {},
        )
        if not assessment.sufficient:
            rejected_at = state.get("tool_count_at_rejection")
            repeated = (
                isinstance(rejected_at, int)
                and rejected_at >= 0
                and rejected_at == state["tool_call_count"]
            )
            if repeated or _acknowledges_gaps(hydrated, assessment.gaps):
                return _accept_incomplete(state, hydrated, assessment)
            events = _append(
                state["events"],
                "evidence_rejected",
                "The outcome was not accepted because primary evidence is incomplete.",
                {"missing_evidence": [gap.model_dump() for gap in assessment.gaps]},
            )
            return {
                "events": events,
                "evidence_feedback": [gap.model_dump() for gap in assessment.gaps],
                "missing_evidence": assessment.details,
                "tool_count_at_rejection": state["tool_call_count"],
                "evidence_validated": False,
                "next_node": "decide",
            }
        events = _append(
            state["events"],
            "output_validated",
            "The recommendation cites only retrieved policy sections and evidence.",
            {"recommended_action": hydrated["action"], "status": state["proposed_status"]},
        )
        return {
            "status": state["proposed_status"],
            "recommended_action": hydrated["action"],
            "summary": hydrated["summary"],
            "findings": hydrated["findings"],
            "citations": hydrated["citations"],
            "unresolved": hydrated["unresolved"],
            "observed_facts": hydrated["observed_facts"],
            "possible_explanations": hydrated["possible_explanations"],
            "missing_evidence": hydrated["missing_evidence"],
            "next_actions": hydrated["next_actions"],
            "evidence_feedback": [],
            "evidence_validated": True,
            "error_code": None,
            "error_detail": None,
            "events": events,
            "next_node": "handoff",
        }

    def handoff(state: InvestigationState) -> dict[str, Any]:
        events = _append(
            state["events"],
            "human_review_required",
            "A person must review this investigation before any financial decision.",
            {"review_required": True, "payment_authority": False},
        )
        return {"events": events, "review_required": True, "next_node": "end"}

    graph = StateGraph(InvestigationState)
    graph.add_node("initialize", initialize)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("decide", decide)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("validate", validate)
    graph.add_node("handoff", handoff)
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "retrieve_context")
    graph.add_conditional_edges(
        "retrieve_context",
        _route,
        {"decide": "decide", "handoff": "handoff"},
    )
    graph.add_conditional_edges(
        "decide",
        _route,
        {"execute_tools": "execute_tools", "validate": "validate", "handoff": "handoff"},
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route,
        {"decide": "decide", "handoff": "handoff"},
    )
    graph.add_conditional_edges(
        "validate",
        _route,
        {"decide": "decide", "handoff": "handoff"},
    )
    graph.add_edge("handoff", END)
    return graph.compile()


def _initial(
    *,
    case_id: UUID,
    reconciliation_run_id: UUID,
    ai_mode: str,
    model: InvestigationModel,
) -> InvestigationState:
    return {
        "case_id": str(case_id),
        "reconciliation_run_id": str(reconciliation_run_id),
        "ai_mode": ai_mode,
        "provider": model.name,
        "model_name": model.model_name,
        "reasoning_kind": model.reasoning_kind,
        "status": InvestigationStatus.FAILED.value,
        "next_node": "initialize",
        "iteration": 0,
        "tool_call_count": 0,
        "deadline": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": "0",
        "tool_results": [],
        "pending_tool_calls": [],
        "evidence": [],
        "events": [],
        "draft": None,
        "proposed_status": None,
        "findings": [],
        "unresolved": [],
        "citations": [],
        "summary": None,
        "recommended_action": None,
        "review_required": True,
        "observed_facts": [],
        "possible_explanations": [],
        "missing_evidence": [],
        "next_actions": [],
        "evidence_feedback": [],
        "evidence_validated": False,
        "tool_count_at_rejection": -1,
        "error_code": None,
        "error_detail": None,
    }


def _result(state: InvestigationState) -> WorkflowResult:
    status = str(state.get("status") or InvestigationStatus.FAILED.value)
    return WorkflowResult(
        status=status,
        recommended_action=state.get("recommended_action"),
        review_required=True,
        summary=state.get("summary"),
        findings=list(state.get("findings") or []),
        unresolved=list(state.get("unresolved") or []),
        citations=list(state.get("citations") or []),
        evidence=list(state.get("evidence") or []),
        events=list(state.get("events") or []),
        error_code=state.get("error_code"),
        error_detail=state.get("error_detail"),
        observed_facts=list(state.get("observed_facts") or []),
        possible_explanations=list(state.get("possible_explanations") or []),
        missing_evidence=list(state.get("missing_evidence") or []),
        next_actions=list(state.get("next_actions") or []),
        evidence_validated=bool(state.get("evidence_validated")),
        input_tokens=int(state.get("input_tokens") or 0),
        output_tokens=int(state.get("output_tokens") or 0),
        estimated_cost_usd=Decimal(str(state.get("estimated_cost_usd") or "0")),
        iteration_count=int(state.get("iteration") or 0),
        tool_call_count=int(state.get("tool_call_count") or 0),
        provider=str(state.get("provider") or ""),
        model_name=str(state.get("model_name") or ""),
        reasoning_kind=str(
            state.get("reasoning_kind") or ReasoningKind.DETERMINISTIC_TEST_DOUBLE.value
        ),
        ai_mode=str(state.get("ai_mode") or "mock"),
    )


def _route(state: InvestigationState) -> str:
    return str(state["next_node"])


def _expired(state: InvestigationState, clock: Clock) -> bool:
    return clock.monotonic() >= float(state["deadline"])


def _stop(
    state: InvestigationState,
    status: InvestigationStatus,
    error_code: str,
    detail: str,
    *,
    iteration: int | None = None,
) -> dict[str, Any]:
    events = _append(
        list(state["events"]),
        "execution_stopped",
        detail,
        {"error_code": error_code, "status": status.value},
    )
    update: dict[str, Any] = {
        "status": status.value,
        "error_code": error_code,
        "error_detail": detail,
        "summary": None,
        "recommended_action": None,
        "findings": [],
        "citations": [],
        "unresolved": [detail],
        "observed_facts": [],
        "possible_explanations": [],
        "missing_evidence": [],
        "next_actions": [],
        "evidence_feedback": [],
        "evidence_validated": False,
        "draft": None,
        "events": events,
        "review_required": True,
        "next_node": "handoff",
    }
    if iteration is not None:
        update["iteration"] = iteration
    return update


def _exhausted(
    state: InvestigationState,
    status: InvestigationStatus,
    error_code: str,
    detail: str,
    *,
    iteration: int | None = None,
) -> dict[str, Any]:
    gaps = [item for item in state.get("missing_evidence") or [] if isinstance(item, str) and item]
    if not gaps:
        return _stop(state, status, error_code, detail, iteration=iteration)
    unresolved = list(gaps)
    if detail not in unresolved:
        unresolved.append(detail)
    summary = (
        "The investigation is inconclusive. Sufficient primary evidence was not "
        "retrieved within the execution limits. Missing evidence: "
        + "; ".join(gaps)
        + ". No invoice was approved and no payment was initiated."
    )
    events = _append(
        list(state["events"]),
        "evidence_inconclusive",
        "The execution limit was reached before the missing evidence was retrieved.",
        {"missing_evidence": gaps, "status": InvestigationStatus.INCONCLUSIVE.value},
    )
    update: dict[str, Any] = {
        "status": InvestigationStatus.INCONCLUSIVE.value,
        "recommended_action": "inconclusive",
        "summary": summary,
        "findings": [],
        "citations": [],
        "unresolved": unresolved,
        "observed_facts": list(state.get("observed_facts") or []),
        "possible_explanations": list(state.get("possible_explanations") or []),
        "missing_evidence": gaps,
        "next_actions": [
            "A person should review the missing evidence before any financial decision."
        ],
        "evidence_feedback": [],
        "evidence_validated": False,
        "error_code": None,
        "error_detail": None,
        "draft": None,
        "events": events,
        "review_required": True,
        "next_node": "handoff",
    }
    if iteration is not None:
        update["iteration"] = iteration
    return update


def _acknowledges_gaps(hydrated: dict[str, Any], gaps: tuple[Any, ...]) -> bool:
    if hydrated.get("action") != "inconclusive":
        return False
    blob = " ".join(
        [
            str(hydrated.get("summary") or ""),
            *[str(item) for item in hydrated.get("unresolved") or []],
            *[str(item) for item in hydrated.get("missing_evidence") or []],
        ]
    ).lower()
    for gap in gaps:
        numbers = [item.lower() for item in gap.document_numbers]
        tokens = [gap.category.lower(), gap.detail.lower(), *numbers]
        if not any(token and token in blob for token in tokens):
            return False
    return True


def _accept_incomplete(
    state: InvestigationState,
    hydrated: dict[str, Any],
    assessment: Any,
) -> dict[str, Any]:
    unresolved = [str(item) for item in hydrated.get("unresolved") or []]
    missing = [str(item) for item in hydrated.get("missing_evidence") or []]
    for detail in assessment.details:
        if detail not in unresolved:
            unresolved.append(detail)
        if detail not in missing:
            missing.append(detail)
    confident = hydrated.get("action") != "inconclusive"
    summary = (
        "The investigation is inconclusive. "
        + " ".join(assessment.details)
        + " No invoice was approved and no payment was initiated."
        if confident
        else str(hydrated.get("summary") or "")
    )
    events = _append(
        list(state["events"]),
        "evidence_inconclusive",
        "The outcome records the evidence that was not retrieved.",
        {"missing_evidence": [gap.model_dump() for gap in assessment.gaps]},
    )
    return {
        "status": InvestigationStatus.INCONCLUSIVE.value,
        "recommended_action": "inconclusive",
        "summary": summary,
        "findings": [] if confident else list(hydrated.get("findings") or []),
        "citations": [] if confident else list(hydrated.get("citations") or []),
        "unresolved": unresolved,
        "observed_facts": list(hydrated.get("observed_facts") or []),
        "possible_explanations": list(hydrated.get("possible_explanations") or []),
        "missing_evidence": missing,
        "next_actions": list(hydrated.get("next_actions") or [])
        or ["A person should review the missing evidence before any financial decision."],
        "evidence_feedback": [],
        "evidence_validated": False,
        "error_code": None,
        "error_detail": None,
        "events": events,
        "review_required": True,
        "next_node": "handoff",
    }


def _invoke_tool(tools: ToolCaller, name: str, arguments: dict[str, Any]) -> ToolExecution:
    try:
        return tools.call(name, arguments)
    except Exception as exc:
        return ToolExecution(
            tool_name=name,
            arguments=_jsonable(arguments),
            ok=False,
            error_code="tool_failed",
            error_detail=exc.__class__.__name__,
            found=False,
        )


def _tool_event(
    events: list[dict[str, Any]],
    execution: ToolExecution,
    *,
    initiator: str,
) -> list[dict[str, Any]]:
    event_type = "tool_completed" if execution.ok else "tool_failed"
    summary = (
        f"{execution.tool_name} returned."
        if execution.ok
        else f"{execution.tool_name} failed ({execution.error_code})."
    )
    payload = {
        "initiator": initiator,
        "arguments": _jsonable(execution.arguments),
        "ok": execution.ok,
        "error_code": execution.error_code,
        "found": execution.found,
        "evidence_labels": execution.evidence_labels,
        "policy_section_codes": [
            section["section_code"]
            for section in execution.data.get("sections", [])
            if isinstance(section, dict) and isinstance(section.get("section_code"), str)
        ],
        "untrusted_instruction_detected": execution.untrusted_instruction_detected,
        "retrieval": execution.data.get("retrieval"),
    }
    updated = _append(events, event_type, summary, payload, tool_name=execution.tool_name)
    if execution.untrusted_instruction_detected:
        updated = _append(
            updated,
            "untrusted_instruction_ignored",
            "Untrusted text contained instruction-like content and was not followed.",
            {"tool_name": execution.tool_name},
            tool_name=execution.tool_name,
        )
    return updated


def _stopped_model(
    state: InvestigationState,
    budgets: InvestigationBudgets,
    iteration: int,
    stop: InvestigationModelStop,
) -> dict[str, Any]:
    input_tokens = state["input_tokens"] + stop.input_tokens
    output_tokens = state["output_tokens"] + stop.output_tokens
    cost = Decimal(state["estimated_cost_usd"]) + stop.estimated_cost_usd
    status = stop.status
    error_code = stop.error_code
    detail = stop.detail
    if cost > budgets.max_estimated_cost_usd and status is not InvestigationStatus.BUDGET_EXCEEDED:
        status = InvestigationStatus.BUDGET_EXCEEDED
        error_code = "cost_limit"
        detail = "The estimated-cost limit was reached."
    events = _append(
        list(state["events"]),
        "model_request_stopped",
        detail,
        {
            "error_code": error_code,
            "input_tokens": stop.input_tokens,
            "output_tokens": stop.output_tokens,
            "estimated_cost_usd": format(stop.estimated_cost_usd, "f"),
        },
    )
    stopped = _exhausted(
        {**state, "events": events},
        status,
        error_code,
        detail,
        iteration=iteration,
    )
    stopped["input_tokens"] = input_tokens
    stopped["output_tokens"] = output_tokens
    stopped["estimated_cost_usd"] = format(cost, "f")
    return stopped


def _observation(
    state: InvestigationState,
    iteration: int,
    budgets: InvestigationBudgets,
    clock: Clock,
) -> DecisionObservation:
    tools: list[ToolObservation] = []
    untrusted = False
    for raw in state["tool_results"]:
        item = ToolObservation.model_validate(
            {
                "tool_name": raw["tool_name"],
                "ok": raw["ok"],
                "error_code": raw.get("error_code"),
                "found": raw.get("found"),
                "evidence_labels": list(raw.get("evidence_labels") or []),
                "data": dict(raw.get("data") or {}),
                "untrusted_instruction_detected": bool(raw.get("untrusted_instruction_detected")),
            }
        )
        tools.append(item)
        untrusted = untrusted or item.untrusted_instruction_detected
    spent = Decimal(state["estimated_cost_usd"])
    remaining_budget = budgets.max_estimated_cost_usd - spent
    if remaining_budget < 0:
        remaining_budget = Decimal("0")
    return DecisionObservation(
        case_id=state["case_id"],
        reconciliation_run_id=state["reconciliation_run_id"],
        tools=tools,
        untrusted_instruction_detected=untrusted,
        iteration=iteration,
        constraints=list(INVESTIGATION_CONSTRAINTS),
        estimated_cost_usd=spent,
        remaining_budget_usd=remaining_budget,
        remaining_seconds=max(0.0, float(state["deadline"]) - clock.monotonic()),
        evidence_feedback=[
            EvidenceGap.model_validate(item) for item in state.get("evidence_feedback") or []
        ],
    )


def _decision_summary(reasoning_kind: str, decision: AgentDecision) -> str:
    actor = (
        "Deterministic test double"
        if reasoning_kind == ReasoningKind.DETERMINISTIC_TEST_DOUBLE.value
        else "Model"
    )
    if decision.action is DecisionAction.CALL_TOOLS:
        names = ", ".join(call.name for call in decision.tool_calls)
        return f"{actor} selected tools: {names}."
    return (
        f"{actor} returned a structured {decision.action.value} decision "
        f"({decision.decision_code})."
    )


def _append(
    events: list[dict[str, Any]],
    event_type: str,
    summary: str,
    payload: dict[str, Any],
    *,
    tool_name: str | None = None,
) -> list[dict[str, Any]]:
    if _FORBIDDEN_EVENT_KEYS & set(payload):
        raise RuntimeError("Investigation events cannot store hidden reasoning.")
    return [
        *events,
        {
            "ordinal": len(events) + 1,
            "event_type": event_type,
            "tool_name": tool_name,
            "summary": summary,
            "payload": payload,
        },
    ]


def _merge_evidence(
    existing: list[dict[str, Any]], execution: ToolExecution
) -> list[dict[str, Any]]:
    if not execution.ok:
        return existing
    seen = {item["label"] for item in existing}
    updated = list(existing)
    for item in execution.evidence:
        if item.label in seen:
            continue
        updated.append(item.model_dump(mode="json"))
        seen.add(item.label)
    return updated


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
