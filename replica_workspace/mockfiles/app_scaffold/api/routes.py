"""__APP_NAME__ REST API routes.

Mounted under /api/env/{env_id}/services/__SERVICE_MOUNT_NAME__
DB session comes from request.state.db_session (IsolationMiddleware).
User impersonation comes from request.state.impersonate_user_id.

Route handlers and route entries are added one at a time during the resource
implementation loop. The request helpers below are universal.
"""

from __future__ import annotations

from typing import Any

from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from sqlalchemy.orm import Session

from ..core.errors import (
    AppAPIError,
    handle_exception,
)
from ..database import operations as ops


# ---------------------------------------------------------------------------
# Request helpers — universal across apps
# ---------------------------------------------------------------------------
#
# These helpers raise ``AppAPIError`` (the base exception class in
# ``core/errors.py``) rather than calling per-status constructors like
# ``unauthorized()`` / ``bad_request()``. App-specific shapes vary across
# replicas: some apps' constructors return ``AppAPIError`` instances (raise
# safe), others return ``JSONResponse`` (raise breaks at runtime because
# ``raise`` needs an ``Exception`` subclass). Raising ``AppAPIError``
# directly is the one shape that's safe regardless of how the implement
# stage chose to write the per-status constructors. ``handle_exception``
# at the handler boundary converts the AppAPIError to the right
# JSONResponse for the app.


def _session(request: Request) -> Session:
    """Get the environment-scoped DB session from request.state."""
    session = getattr(request.state, "db_session", None)
    if session is None:
        raise AppAPIError(
            message="Missing database session",
            http_code=status.HTTP_401_UNAUTHORIZED,
        )
    return session


def _principal_user_id(request: Request) -> str:
    """Resolve the acting principal from request state."""
    principal = getattr(request.state, "impersonate_user_id", None)
    if principal is not None and str(principal).strip() != "":
        return str(principal)
    raise AppAPIError(
        message="Missing user authentication",
        http_code=status.HTTP_401_UNAUTHORIZED,
    )


async def _parse_json_body(request: Request) -> dict[str, Any]:
    """Parse JSON body. Raises an app-shaped 400 on malformed input."""
    try:
        return await request.json()
    except Exception as exc:
        raise AppAPIError(
            message=f"Invalid JSON body: {exc}",
            http_code=status.HTTP_400_BAD_REQUEST,
        ) from exc


def _pagination_params(request: Request) -> tuple[str | None, int]:
    """Extract cursor and limit from query params (cursor-based pagination)."""
    cursor = request.query_params.get("cursor")
    limit_str = request.query_params.get("limit")
    limit = 50
    if limit_str is not None:
        try:
            limit = max(1, min(200, int(limit_str)))
        except ValueError:
            pass
    return cursor, limit


# ---------------------------------------------------------------------------
# Endpoint handlers — added per entity by entity scaffold
# ---------------------------------------------------------------------------

# AGENT INSTRUCTION: Add endpoint handler functions here during entity
# implementation. Each handler follows this pattern:
#
#   async def <operation>_<entity>(request: Request) -> JSONResponse:
#       try:
#           session = _session(request)
#           # ... extract params, call ops, serialize ...
#           return JSONResponse(payload, status_code=status.HTTP_200_OK)
#       except AppAPIError as exc:
#           return exc.to_response()
#       except Exception as exc:
#           return handle_exception(exc)


# ---------------------------------------------------------------------------
# Unknown-endpoint catch-all — universal across apps
# ---------------------------------------------------------------------------
#
# Any request whose path does not match a real route in the table below
# lands here. Returns a 404 with the app's native error envelope, so an
# agent calling an unimplemented endpoint during development sees a
# response that is shape-indistinguishable from a real upstream "no such
# endpoint" 404 — not Starlette's default plain-text ``"Not Found"`` and
# not the IsolationMiddleware's ``{"ok": false, "error": "internal_error"}``
# 500 (which would otherwise fire if anything in this handler raised).
#
# We construct the AppAPIError directly here rather than calling the
# convenience helper ``not_found(...)``. Two reasons:
#
#   1. Per-app convention varies. Some apps' generated ``not_found(...)``
#      returns an ``AppAPIError`` instance (raise-safe, has ``to_response``).
#      Others return a ``JSONResponse`` directly. Calling ``.to_response()``
#      on a JSONResponse blows up with AttributeError, which the platform
#      middleware then catches as an unhandled exception and rewrites to a
#      generic 500. Going through ``AppAPIError(...)`` directly is the one
#      shape that's safe regardless of which convention the implement
#      stage chose.
#   2. It's the same pattern the request helpers above use (``_session``,
#      ``_principal_user_id``, ``_parse_json_body``). Consistent.

def _api_relative_path(full_path: str) -> str:
    """Strip the platform's env-routing prefix to get the API-relative path.

    Requests reach this handler with paths like
    ``/api/env/<env_id>/services/<service_name>/<rest>``. The
    ``<rest>`` portion is what an agent would see if it were talking to
    the real upstream API. Echoing the env-routing prefix in error
    messages would tip the agent off that it's running against a
    multi-tenant replica platform rather than the upstream itself.
    """
    if "/services/" in full_path:
        parts = full_path.split("/services/", 1)
        after_services = parts[1]
        slash_index = after_services.find("/")
        if slash_index >= 0:
            return after_services[slash_index:]
        return "/"
    return full_path


async def unknown_endpoint(request: Request) -> JSONResponse:
    """Catch-all handler for requests that match no real route."""
    return AppAPIError(
        message=f"Endpoint not found: {request.method} {_api_relative_path(request.url.path)}",
        http_code=status.HTTP_404_NOT_FOUND,
    ).to_response()


# ---------------------------------------------------------------------------
# Route table — entries added per entity by entity scaffold
# ---------------------------------------------------------------------------

# AGENT INSTRUCTION: Add new Route entries ABOVE the catch-all at the
# bottom of this list. Two hard rules:
#
#   1. Fixed paths (e.g. /projects/archived) must come before parameterized
#      paths (e.g. /projects/{project_id}) so Starlette matches them first.
#   2. The ``/{_unknown_path:path}`` catch-all must always remain the LAST
#      entry in the list. Starlette matches in order, so any route placed
#      after it would be unreachable.

routes: list[Route] = [
    # --- Real endpoints go here (added by the entity implementation loop) ---

    # --- Catch-all — MUST be the last entry ---
    Route(
        "/{_unknown_path:path}",
        unknown_endpoint,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    ),
]
