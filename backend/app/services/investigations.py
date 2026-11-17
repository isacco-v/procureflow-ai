"""Start an investigation for a reconciliation run and store its audit trail.

A repeat request for the same run and AI mode returns the latest stored
attempt. It does not start another model run. A new attempt is created only
when the caller sends an explicit attempt header and an idempotency key.
Earlier attempts, including a mock row and a failed live row, stay unchanged.
The workflow is synchronous and read-only.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.gating import live_investigation_allowed
from app.ai.investigation import InvestigationModel, build_investigation_model
from app.ai.provider import RealProviderDisabledError
from app.core.config import Settings
from app.db.models import (
    Investigation,
    InvestigationCitation,
    InvestigationEvent,
    InvestigationEvidence,
)
from app.domain.investigation import InvestigationBudgets
from app.domain.matching.models import MatchStatus
from app.services.cases import get_case
from app.services.errors import ConflictError, ForbiddenError, NotFoundError, ProcurementError
from app.services.investigation_tools import ToolExecutor
from app.services.investigation_workflow import Clock, WorkflowResult, run_workflow
from app.services.policy_seed import ensure_policy_corpus
from app.services.reconciliation import get_reconciliation

_INVESTIGATABLE = frozenset({MatchStatus.EXCEPTION.value, MatchStatus.NEEDS_REVIEW.value})
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
_LOAD = (
    selectinload(Investigation.events),
    selectinload(Investigation.evidence),
    selectinload(Investigation.citations),
)


@dataclass(frozen=True)
class StoredInvestigation:
    investigation: Investigation
    created: bool


def budgets_from_settings(settings: Settings) -> InvestigationBudgets:
    return InvestigationBudgets(
        max_iterations=settings.investigation_max_iterations,
        max_tool_calls=settings.investigation_max_tool_calls,
        timeout_seconds=settings.investigation_timeout_seconds,
        max_estimated_cost_usd=settings.investigation_max_estimated_cost_usd,
    )


def start_investigation(
    session: Session,
    case_id: UUID,
    run_id: UUID,
    settings: Settings,
    *,
    model: InvestigationModel | None = None,
    clock: Clock | None = None,
    budgets: InvestigationBudgets | None = None,
    new_attempt: bool = False,
    idempotency_key: str | None = None,
) -> StoredInvestigation:
    run = get_reconciliation(session, case_id, run_id)
    if run.status not in _INVESTIGATABLE:
        raise ConflictError(
            "investigation_not_applicable",
            "Investigation runs only for EXCEPTION or NEEDS_REVIEW reconciliations.",
        )
    key = _checked_key(idempotency_key, required=new_attempt)
    if new_attempt:
        stored_key = _find_by_key(session, case_id, run_id, settings.ai_mode, key or "")
        if stored_key is not None:
            return StoredInvestigation(stored_key, created=False)
        attempt = _next_attempt(session, run_id, settings.ai_mode)
    else:
        existing = _find(session, case_id, run_id, ai_mode=settings.ai_mode)
        if existing is not None:
            return StoredInvestigation(existing, created=False)
        if key is not None:
            stored_key = _find_by_key(session, case_id, run_id, settings.ai_mode, key)
            if stored_key is not None:
                return StoredInvestigation(stored_key, created=False)
        attempt = 1

    try:
        selected = model if model is not None else build_investigation_model(settings)
    except RealProviderDisabledError as exc:
        raise ForbiddenError("live_investigation_disabled", str(exc)) from exc
    if settings.ai_mode != "mock" and not live_investigation_allowed(settings):
        raise ForbiddenError(
            "live_investigation_disabled",
            "Live investigation is disabled. No model request is sent.",
        )

    ensure_policy_corpus(session)
    started = datetime.now(UTC)
    try:
        result = run_workflow(
            case_id=case_id,
            reconciliation_run_id=run_id,
            ai_mode=settings.ai_mode,
            model=selected,
            tools=ToolExecutor(
                session,
                case_id=case_id,
                reconciliation_run_id=run_id,
            ),
            budgets=budgets or budgets_from_settings(settings),
            clock=clock,
        )
    except Exception as exc:
        session.rollback()
        _persist_failure(
            session,
            case_id,
            run_id,
            started,
            exc.__class__.__name__,
            ai_mode=settings.ai_mode,
            provider=selected.name,
            model_name=selected.model_name,
            reasoning_kind=selected.reasoning_kind,
            attempt=attempt,
            idempotency_key=key,
        )
        raise ProcurementError(
            "investigation_failed",
            "The investigation failed before it could produce a recommendation.",
            500,
        ) from exc

    investigation = _insert(
        session,
        case_id,
        run_id,
        started,
        result,
        attempt=attempt,
        idempotency_key=key,
        renumber=new_attempt,
    )
    if investigation is None:
        raced = _find_by_key(session, case_id, run_id, settings.ai_mode, key or "")
        if raced is None and not new_attempt:
            raced = _find(session, case_id, run_id, ai_mode=settings.ai_mode)
        if raced is not None:
            return StoredInvestigation(raced, created=False)
        raise ProcurementError(
            "investigation_not_stored",
            "The investigation could not be stored.",
            500,
        )
    stored = session.scalar(
        select(Investigation).where(Investigation.id == investigation.id).options(*_LOAD)
    )
    if stored is None:
        raise ProcurementError(
            "investigation_not_stored",
            "The investigation could not be reloaded.",
            500,
        )
    return StoredInvestigation(stored, created=True)


def get_investigation(session: Session, case_id: UUID, investigation_id: UUID) -> Investigation:
    get_case(session, case_id)
    investigation = session.scalar(
        select(Investigation)
        .where(Investigation.id == investigation_id, Investigation.case_id == case_id)
        .options(*_LOAD)
    )
    if investigation is None:
        raise NotFoundError("investigation_not_found", "Investigation was not found.")
    return investigation


def get_investigation_for_run(
    session: Session, case_id: UUID, run_id: UUID, ai_mode: str
) -> Investigation:
    get_reconciliation(session, case_id, run_id)
    investigation = _find(session, case_id, run_id, ai_mode=ai_mode)
    if investigation is None:
        raise NotFoundError(
            "investigation_not_found",
            "This reconciliation run has no investigation for the configured AI mode.",
        )
    return investigation


def _find(session: Session, case_id: UUID, run_id: UUID, *, ai_mode: str) -> Investigation | None:
    return session.scalar(
        select(Investigation)
        .where(
            Investigation.case_id == case_id,
            Investigation.reconciliation_run_id == run_id,
            Investigation.ai_mode == ai_mode,
        )
        .order_by(Investigation.attempt.desc())
        .options(*_LOAD)
        .limit(1)
    )


def _find_by_key(
    session: Session,
    case_id: UUID,
    run_id: UUID,
    ai_mode: str,
    idempotency_key: str,
) -> Investigation | None:
    if not idempotency_key:
        return None
    return session.scalar(
        select(Investigation)
        .where(
            Investigation.case_id == case_id,
            Investigation.reconciliation_run_id == run_id,
            Investigation.ai_mode == ai_mode,
            Investigation.idempotency_key == idempotency_key,
        )
        .options(*_LOAD)
    )


def _next_attempt(session: Session, run_id: UUID, ai_mode: str) -> int:
    current = session.scalar(
        select(func.max(Investigation.attempt)).where(
            Investigation.reconciliation_run_id == run_id,
            Investigation.ai_mode == ai_mode,
        )
    )
    return int(current or 0) + 1


def _checked_key(value: str | None, *, required: bool) -> str | None:
    if value is None or value.strip() == "":
        if required:
            raise ConflictError(
                "attempt_key_required",
                "A new investigation attempt requires an Idempotency-Key.",
            )
        return None
    if _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise ConflictError(
            "invalid_attempt_request",
            "The Idempotency-Key is not valid for an investigation attempt.",
        )
    return value


def _persist_failure(
    session: Session,
    case_id: UUID,
    run_id: UUID,
    started: datetime,
    error_name: str,
    *,
    ai_mode: str,
    provider: str,
    model_name: str,
    reasoning_kind: str,
    attempt: int,
    idempotency_key: str | None,
) -> None:
    if idempotency_key and _find_by_key(session, case_id, run_id, ai_mode, idempotency_key):
        return
    finished = datetime.now(UTC)
    investigation_id = uuid4()
    investigation = Investigation(
        id=investigation_id,
        case_id=case_id,
        reconciliation_run_id=run_id,
        attempt=attempt,
        idempotency_key=idempotency_key,
        evidence_validated=False,
        status="failed",
        ai_mode=ai_mode,
        provider=provider,
        model_name=model_name,
        reasoning_kind=reasoning_kind,
        recommended_action=None,
        review_required=True,
        summary=None,
        structured_findings=[],
        unresolved_issues=["The investigation failed."],
        observed_facts=[],
        possible_explanations=[],
        missing_evidence=["The investigation failed before it could retrieve evidence."],
        next_actions=[],
        prerequisites=[],
        error_code="workflow_failed",
        error_detail=error_name,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=Decimal("0"),
        iteration_count=0,
        tool_call_count=0,
        started_at=started,
        finished_at=finished,
    )
    investigation.events = [
        InvestigationEvent(
            investigation_id=investigation_id,
            ordinal=1,
            event_type="execution_stopped",
            tool_name=None,
            summary="The investigation failed before it could produce a recommendation.",
            payload={"error_code": "workflow_failed"},
        )
    ]
    investigation.evidence = []
    investigation.citations = []
    session.add(investigation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()


def _insert(
    session: Session,
    case_id: UUID,
    run_id: UUID,
    started: datetime,
    result: WorkflowResult,
    *,
    attempt: int,
    idempotency_key: str | None,
    renumber: bool,
) -> Investigation | None:
    current = attempt
    for _ in range(2 if renumber else 1):
        investigation = _build(
            case_id,
            run_id,
            started,
            result,
            attempt=current,
            idempotency_key=idempotency_key,
        )
        session.add(investigation)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if idempotency_key and _find_by_key(
                session, case_id, run_id, result.ai_mode, idempotency_key
            ):
                return None
            if not renumber:
                return None
            current = _next_attempt(session, run_id, result.ai_mode)
            continue
        return investigation
    return None


def _build(
    case_id: UUID,
    run_id: UUID,
    started: datetime,
    result: WorkflowResult,
    *,
    attempt: int,
    idempotency_key: str | None,
) -> Investigation:
    investigation_id = uuid4()
    finished = datetime.now(UTC)
    investigation = Investigation(
        id=investigation_id,
        case_id=case_id,
        reconciliation_run_id=run_id,
        attempt=attempt,
        idempotency_key=idempotency_key,
        evidence_validated=result.evidence_validated,
        status=result.status,
        ai_mode=result.ai_mode,
        provider=result.provider,
        model_name=result.model_name,
        reasoning_kind=result.reasoning_kind,
        recommended_action=result.recommended_action,
        review_required=True,
        summary=result.summary,
        structured_findings=result.findings,
        unresolved_issues=result.unresolved,
        observed_facts=result.observed_facts,
        possible_explanations=result.possible_explanations,
        missing_evidence=result.missing_evidence,
        next_actions=result.next_actions,
        prerequisites=result.prerequisites,
        error_code=result.error_code,
        error_detail=result.error_detail,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        iteration_count=result.iteration_count,
        tool_call_count=result.tool_call_count,
        started_at=started,
        finished_at=finished,
    )
    investigation.events = [
        InvestigationEvent(
            investigation_id=investigation_id,
            ordinal=int(event["ordinal"]),
            event_type=str(event["event_type"]),
            tool_name=event.get("tool_name"),
            summary=str(event["summary"]),
            payload=dict(event.get("payload") or {}),
        )
        for event in result.events
    ]
    investigation.evidence = [
        InvestigationEvidence(
            investigation_id=investigation_id,
            ordinal=ordinal,
            tool_name=str(item["tool_name"]),
            record_type=str(item["record_type"]),
            record_id=_optional_uuid(item.get("record_id")),
            label=str(item["label"]),
        )
        for ordinal, item in enumerate(result.evidence, start=1)
    ]
    investigation.citations = [
        InvestigationCitation(
            investigation_id=investigation_id,
            policy_section_id=UUID(str(item["policy_section_id"])),
            ordinal=ordinal,
            policy_code=str(item["policy_code"]),
            section_code=str(item["section_code"]),
            version=str(item["version"]),
            heading=str(item["heading"]),
            excerpt=str(item["excerpt"]),
        )
        for ordinal, item in enumerate(result.citations, start=1)
    ]
    return investigation


def _optional_uuid(value: object) -> UUID | None:
    if value is None or value == "":
        return None
    return UUID(str(value))
