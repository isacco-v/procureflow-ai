"""Procurement service errors. HTTP adapters map these to response envelopes."""


class ProcurementError(Exception):
    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class NotFoundError(ProcurementError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, 404)


class ConflictError(ProcurementError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, 409)


class ForbiddenError(ProcurementError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, 403)


class UnavailableError(ProcurementError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, 503)


class SeedUnavailableError(ProcurementError):
    def __init__(self) -> None:
        super().__init__(
            "seed_unavailable",
            "Synthetic seed is only available when APP_ENV is local, test, or development.",
            404,
        )
