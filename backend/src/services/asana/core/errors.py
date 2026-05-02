"""Error primitives for the Asana API replica.

Asana's error envelope wraps a list of error objects:

    {"errors": [{"message": "...", "help": "...", "phrase": "..."}]}

`help` and `phrase` are optional per the spec; `phrase` is only set on 500s.
"""

from __future__ import annotations

from starlette import status
from starlette.responses import JSONResponse


# ---------------------------------------------------------------------------
# Base error class — Asana-shaped error envelope
# ---------------------------------------------------------------------------

class AppAPIError(Exception):
    """Base Asana-shaped API error."""

    def __init__(
        self,
        message: str,
        *,
        http_code: int = status.HTTP_400_BAD_REQUEST,
        help: str | None = None,
        phrase: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_code = http_code
        self.help = help
        self.phrase = phrase

    def to_dict(self) -> dict:
        error_obj: dict = {"message": self.message}
        if self.help is not None:
            error_obj["help"] = self.help
        if self.phrase is not None:
            error_obj["phrase"] = self.phrase
        return {"errors": [error_obj]}

    def to_response(self) -> JSONResponse:
        return JSONResponse(content=self.to_dict(), status_code=self.http_code)


# ---------------------------------------------------------------------------
# Convenience constructors — one per HTTP error reachable from the spec.
# Each returns a JSONResponse shaped to match the Asana error schema.
# ---------------------------------------------------------------------------

def _error_body(detail: str, phrase: str | None = None) -> dict:
    error_obj: dict = {"message": detail}
    if phrase is not None:
        error_obj["phrase"] = phrase
    return {"errors": [error_obj]}


def bad_request(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


def payment_required(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
    )


def forbidden(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_403_FORBIDDEN,
    )


def not_found(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_404_NOT_FOUND,
    )


def unprocessable_entity(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


def too_many_requests(detail: str) -> JSONResponse:
    return JSONResponse(
        content=_error_body(detail),
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def internal_server_error(detail: str) -> JSONResponse:
    # Per the Asana spec, 500 responses include a `phrase` for support lookup.
    return JSONResponse(
        content=_error_body(detail, phrase="replica internal error"),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---------------------------------------------------------------------------
# Catch-all — maps known internal exceptions to the right constructor and
# falls back to internal_server_error for anything unexpected.
# ---------------------------------------------------------------------------

def handle_exception(exc: Exception) -> JSONResponse:
    """Convert unhandled exceptions into an Asana-shaped error response."""
    if isinstance(exc, AppAPIError):
        return exc.to_response()
    if isinstance(exc, PermissionError):
        return forbidden(str(exc) or "Forbidden")
    if isinstance(exc, LookupError):
        # KeyError, IndexError — typically a missing resource lookup.
        return not_found(str(exc) or "Not Found")
    if isinstance(exc, ValueError):
        return bad_request(str(exc) or "Bad Request")
    if isinstance(exc, NotImplementedError):
        return internal_server_error(str(exc) or "Not Implemented")
    return internal_server_error(f"Internal server error: {exc}")
