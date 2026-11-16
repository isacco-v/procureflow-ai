"""Versioned procurement routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.presenters import case_detail, case_summary, reconciliation_response
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.procurement import (
    CaseDetailResponse,
    CaseListResponse,
    ReconciliationResponse,
    SeedResponse,
)
from app.services.cases import get_case, list_cases
from app.services.reconciliation import (
    get_reconciliation,
    latest_reconciliation,
    run_reconciliation,
)
from app.services.seed import assert_seed_allowed, seed_synthetic_cases

router = APIRouter(prefix="/api/v1", tags=["procurement"])


@router.get("/cases", response_model=CaseListResponse)
def read_cases(session: Annotated[Session, Depends(get_db)]) -> CaseListResponse:
    return CaseListResponse(cases=[case_summary(row) for row in list_cases(session)])


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
def read_case(
    case_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    case = get_case(session, case_id)
    latest = next(
        iter(
            sorted(
                case.reconciliation_runs,
                key=lambda run: (run.created_at, run.id),
                reverse=True,
            )
        ),
        None,
    )
    return case_detail(case, latest)


@router.post("/cases/{case_id}/reconciliation", response_model=ReconciliationResponse)
def create_reconciliation(
    case_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> ReconciliationResponse:
    stored = run_reconciliation(session, case_id)
    response.status_code = status.HTTP_201_CREATED if stored.created else status.HTTP_200_OK
    return reconciliation_response(stored.run, replayed=not stored.created)


@router.get("/cases/{case_id}/reconciliation", response_model=ReconciliationResponse)
def read_latest_reconciliation(
    case_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> ReconciliationResponse:
    return reconciliation_response(latest_reconciliation(session, case_id), replayed=False)


@router.get(
    "/cases/{case_id}/reconciliation/{run_id}",
    response_model=ReconciliationResponse,
)
def read_reconciliation(
    case_id: UUID,
    run_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> ReconciliationResponse:
    return reconciliation_response(get_reconciliation(session, case_id, run_id), replayed=False)


@router.post("/dev/seed", response_model=SeedResponse)
def seed_cases(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SeedResponse:
    assert_seed_allowed(settings.app_env)
    result = seed_synthetic_cases(session)
    return SeedResponse(cases_created=list(result.created), cases_existing=list(result.existing))
