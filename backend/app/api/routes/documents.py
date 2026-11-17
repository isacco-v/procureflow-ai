"""Versioned document intake routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.document_presenters import accept_response, upload_detail, upload_summary
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.documents import (
    AcceptDocumentResponse,
    UploadDetailResponse,
    UploadListResponse,
)
from app.services.documents import (
    accept_upload,
    assess_upload,
    get_upload,
    intake_pdf,
    list_uploads,
    read_limited,
    requested_provider,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.get("/documents", response_model=UploadListResponse)
def read_documents(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadListResponse:
    provider = requested_provider(settings)
    return UploadListResponse(
        documents=[
            upload_summary(row, duplicate=False, provider=provider) for row in list_uploads(session)
        ]
    )


@router.post("/documents", response_model=UploadDetailResponse)
def create_document(
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
) -> UploadDetailResponse:
    data = read_limited(file.file, settings.document_max_bytes)
    assess_upload(data, file.content_type, max_bytes=settings.document_max_bytes)
    stored = intake_pdf(
        session,
        settings,
        data=data,
        filename=file.filename,
        media_type=file.content_type,
    )
    response.status_code = status.HTTP_200_OK if stored.duplicate else status.HTTP_201_CREATED
    return upload_detail(
        stored.upload, duplicate=stored.duplicate, provider=requested_provider(settings)
    )


@router.get("/documents/{document_id}", response_model=UploadDetailResponse)
def read_document(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadDetailResponse:
    return upload_detail(
        get_upload(session, document_id),
        duplicate=False,
        provider=requested_provider(settings),
    )


@router.post("/documents/{document_id}/accept", response_model=AcceptDocumentResponse)
def accept_document(
    document_id: UUID,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AcceptDocumentResponse:
    result = accept_upload(session, document_id, settings)
    response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
    return accept_response(result)
