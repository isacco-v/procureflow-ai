import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes.health import router as health_router
from app.api.routes.procurement import router as procurement_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.errors import ProcurementError

logger = logging.getLogger("app.access")
_REQUEST_ID_MAX_LENGTH = 128


def _request_id(header_value: str | None) -> str:
    if header_value is None:
        return str(uuid.uuid4())
    candidate = header_value.strip()
    if (
        not candidate
        or len(candidate) > _REQUEST_ID_MAX_LENGTH
        or not candidate.isascii()
        or not candidate.isprintable()
    ):
        return str(uuid.uuid4())
    return candidate


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        summary="Procurement cases and deterministic three-way reconciliation.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request.headers.get("x-request-id"))
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(ProcurementError)
    def handle_procurement_error(_request: Request, exc: ProcurementError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "detail": exc.detail},
        )

    app.include_router(health_router)
    app.include_router(procurement_router)
    return app


app = create_app()
