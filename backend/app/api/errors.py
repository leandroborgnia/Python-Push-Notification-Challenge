from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    ForbiddenError,
    InvalidSendError,
    NotFoundError,
    TokenError,
    ValidationError,
)

# Most specific first; the first matching base class wins.
_STATUS_BY_ERROR: tuple[tuple[type[DomainError], int], ...] = (
    (ConflictError, 409),
    (NotFoundError, 404),
    (ForbiddenError, 403),
    (AuthenticationError, 400),
    (TokenError, 400),
    (InvalidSendError, 400),
    (ValidationError, 422),
)


def _status_for(exc: Exception) -> int:
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            return code
    return 400  # generic DomainError fallback


def install_exception_handlers(app: FastAPI) -> None:
    """Map domain errors to HTTP status codes centrally so routers stay thin."""

    async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=_status_for(exc), content={"detail": str(exc)})

    app.add_exception_handler(DomainError, handle_domain_error)
