"""Every error leaves the API as the contract's `ApiError` body, with the request's id."""

import logging
import re
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("api")

MAX_TEXT = 500  # LIMITS.errorTextMaxChars

_STATUS_NAMES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    422: "validation_error",
    503: "service_unavailable",
}


class ApiException(Exception):
    """Raise anywhere in a route to return `ApiError` with this status."""

    def __init__(self, status: int, error: str, detail: str | None = None):
        self.status, self.error, self.detail = status, error, detail
        super().__init__(f"{status} {error}: {detail}")


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(request: Request, status: int, error: str, detail: str | None) -> JSONResponse:
    body = {"error": error, "detail": _clip(detail), "request_id": request_id_of(request)}
    return JSONResponse(body, status_code=status)


def summarise_validation(errors: list[dict[str, Any]]) -> str:
    parts = []
    for e in errors[:5]:
        loc = ".".join(str(p) for p in e.get("loc", ()) if p != "body") or "<body>"
        parts.append(f"{loc}: {e.get('msg', 'invalid')}")
    more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
    return "; ".join(parts) + more


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api_exception(request: Request, exc: ApiException):
        return error_response(request, exc.status, exc.error, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "validation_error", summarise_validation(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        error = _STATUS_NAMES.get(exc.status_code, f"http_{exc.status_code}")
        detail = str(exc.detail)
        if exc.status_code == 404 and detail == "Not Found":
            detail = f"No route for {request.method} {request.url.path} (see /docs)."
        return error_response(request, exc.status_code, error, detail)

    @app.exception_handler(psycopg.OperationalError)
    async def _db_down(request: Request, exc: psycopg.OperationalError):
        log.error("database unavailable (request_id=%s): %s", request_id_of(request), exc)
        return error_response(
            request, 503, "database_unavailable", "The database is not reachable; is it running?"
        )

    @app.exception_handler(psycopg.errors.UndefinedTable)
    async def _not_migrated(request: Request, exc: psycopg.errors.UndefinedTable):
        log.error("schema missing (request_id=%s): %s", request_id_of(request), exc)
        return error_response(
            request,
            503,
            "database_not_ready",
            "The database has no tables yet; run `pnpm ingest:snapshot` first.",
        )


def internal_error(request: Request, exc: Exception) -> JSONResponse:
    """Called by the request-context middleware for anything unhandled (a bug)."""
    log.exception("unhandled error (request_id=%s)", request_id_of(request), exc_info=exc)
    return error_response(
        request,
        500,
        "internal_error",
        "Unexpected server error. Quote the request_id when reporting it.",
    )


_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def acceptable_request_id(value: str | None) -> str | None:
    return value if value and _ID_OK.match(value) else None
