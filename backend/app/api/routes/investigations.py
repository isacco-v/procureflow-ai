"""Versioned investigation routes.

Starting an investigation does not accept a caller-supplied prompt. The case
and reconciliation run are the only inputs. A repeat call returns the stored
investigation for the process AI mode. It does not return the other mode.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.api.presenters import investigation_events, investigation_response
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.investigation import InvestigationEventListResponse, InvestigationResponse
from app.services.errors import ConflictError
from app.services.investigations import (
    get_investigation,
    get_investigation_for_run,
    start_investigation,
)

router = APIRouter(prefix="/api/v1", tags=["investigations"])


@router.post(
    "/cases/{case_id}/reconciliation/{run_id}/investigations",
    response_model=InvestigationResponse,
)
def create_investigation(
    case_id: UUID,
    run_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    investigation_attempt: Annotated[str | None, Header(alias="X-Investigation-Attempt")] = None,
) -> InvestigationResponse:
    if investigation_attempt not in (None, "new"):
        raise ConflictError(
            "invalid_attempt_request",
            "X-Investigation-Attempt must be omitted or set to new.",
        )
    stored = start_investigation(
        session,
        case_id,
        run_id,
        settings,
        new_attempt=investigation_attempt == "new",
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if stored.created else status.HTTP_200_OK
    return investigation_response(stored.investigation, replayed=not stored.created)


@router.get(
    "/cases/{case_id}/reconciliation/{run_id}/investigation",
    response_model=InvestigationResponse,
)
def read_investigation_for_run(
    case_id: UUID,
    run_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvestigationResponse:
    return investigation_response(
        get_investigation_for_run(session, case_id, run_id, settings.ai_mode),
        replayed=False,
    )


@router.get(
    "/cases/{case_id}/investigations/{investigation_id}",
    response_model=InvestigationResponse,
)
def read_investigation(
    case_id: UUID,
    investigation_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> InvestigationResponse:
    return investigation_response(
        get_investigation(session, case_id, investigation_id),
        replayed=False,
    )


@router.get(
    "/cases/{case_id}/investigations/{investigation_id}/events",
    response_model=InvestigationEventListResponse,
)
def read_investigation_events(
    case_id: UUID,
    investigation_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> InvestigationEventListResponse:
    return investigation_events(get_investigation(session, case_id, investigation_id))
