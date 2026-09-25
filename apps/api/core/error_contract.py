"""RFC 9457-compatible common error contract.

Normalizes framework / domain errors into a single Problem Details-style JSON
body so the frontend can consume a clean contract (``code`` / ``pointer`` /
``request_id``) instead of defensively parsing raw Pydantic detail.

Captured set is fixed to three handlers:

- :class:`fastapi.exceptions.RequestValidationError` -> 422
- :class:`starlette.exceptions.HTTPException` -> ``exc.status_code``
- :class:`Exception` catch-all -> 500 (never echoes ``str(exc)`` in the body)

Design rules:

- ``input`` (reflected user input) is never emitted structurally; this closes
  the secret-leak path (CWE-209). Raw pydantic ``msg`` is not surfaced either.
- ``type`` is fixed to ``about:blank`` (no problem-type URI registry).
- ``request_id`` / ``X-Request-ID`` is the single correlation id, sourced from
  the request-id middleware in ``apps/api/application.py``.
- The HTTP status line and body ``status`` are set by each handler per RFC /
  framework convention. ``code`` is an independent machine-readable classifier;
  clients read ``status`` and must not recompute HTTP status from ``code``.
  Validation is always 422; :func:`get_http_status_for_error_code` does not
  govern validation responses.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.core.config import get_api_settings
from apps.api.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = get_logger(__name__)

PROBLEM_TYPE = "about:blank"
PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"

# Fixed, user-safe human message for validation failures. The specific field
# problems live in ``errors[]``; the raw pydantic ``msg`` / ``input`` are never
# surfaced to the user (they may reflect secrets).
VALIDATION_DETAIL = "入力内容を確認してください"

# Generic user-safe fallbacks by status class.
_FALLBACK_4XX = "リクエストを確認してください"
_FALLBACK_5XX = "サーバーで問題が発生しました。時間をおいて再試行してください"

# Field-level validation code: a small, stable set (NOT the E-code system).
# Pydantic v2 error ``type`` -> stable field code.
_FIELD_CODE_BY_PYDANTIC_TYPE: dict[str, str] = {
    "missing": "required",
    "string_too_short": "too_short",
    "too_short": "too_short",
    "string_too_long": "too_long",
    "too_long": "too_long",
    "string_pattern_mismatch": "invalid_format",
    "value_error": "invalid",
    "json_invalid": "invalid_format",
    "enum": "invalid",
}

_FIELD_CODE_FALLBACK = "invalid"


def _field_code(pydantic_type: str) -> str:
    """Map a pydantic error ``type`` to a stable field-level code.

    Unknown / parsing / coercion types collapse to ``invalid_format`` (parsing)
    or the generic ``invalid`` fallback so the emitted set stays small.
    """
    mapped = _FIELD_CODE_BY_PYDANTIC_TYPE.get(pydantic_type)
    if mapped is not None:
        return mapped
    if pydantic_type.endswith(("_parsing", "_type")):
        return "invalid_format"
    return _FIELD_CODE_FALLBACK


def _json_pointer(loc: tuple[Any, ...]) -> str:
    """Convert a pydantic ``loc`` tuple to an RFC 6901 JSON Pointer.

    The leading ``body`` segment (present for request-body validation) is
    stripped so the pointer matches the client-facing field path; ``query`` /
    ``path`` prefixes are preserved. Array indices become numeric segments.
    """
    parts = list(loc)
    if parts and parts[0] == "body":
        parts = parts[1:]
    if not parts:
        return "/"
    return "/" + "/".join(str(part) for part in parts)


def _title_for(status_code: int) -> str:
    """Human-readable HTTP status phrase (e.g. ``Unprocessable Entity``)."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _request_id(request: Request) -> str:
    """Read the request id set by the request-id middleware."""
    return getattr(request.state, "request_id", "unknown")


def build_problem_response(
    *,
    status_code: int,
    detail: Any,
    request_id: str,
    code: str | None = None,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Assemble an RFC 9457-compatible JSON response body.

    ``code`` and ``errors`` are additive: omitted when ``None`` so simple
    responses stay lean while validation responses carry field detail.
    """
    body: dict[str, Any] = {
        "type": PROBLEM_TYPE,
        "title": _title_for(status_code),
        "status": status_code,
        "detail": detail,
    }
    if code is not None:
        body["code"] = code
    if errors is not None:
        body["errors"] = errors
    body["request_id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=headers,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
    )


def build_validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Map a ``RequestValidationError`` to ``errors[]`` (pointer + code).

    Single source of truth for the pointer / code mapping so routers that need
    to enrich the entries stay in sync with :func:`request_validation_handler`.
    ``input`` / ``msg`` are never carried over.
    """
    return [
        {
            "pointer": _json_pointer(tuple(err.get("loc", ()))),
            "code": _field_code(str(err.get("type", ""))),
        }
        for err in exc.errors()
    ]


async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 handler: emit ``errors[]`` (pointer + code) without ``input`` / ``msg``."""
    return build_problem_response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        detail=VALIDATION_DETAIL,
        code="E4001",
        errors=build_validation_errors(exc),
        request_id=_request_id(request),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """HTTPException handler: preserve ``exc.status_code`` and normalize ``detail``.

    ``detail`` is kept as a human-readable string. Routers may also raise
    ``HTTPException(detail={"error_code", "message"})``; that dict shape is
    preserved, and its ``error_code`` is surfaced as the top-level ``code``.
    """
    status_code = exc.status_code
    # Starlette types `detail` as str | None, but FastAPI routers may raise
    # HTTPException(detail={...}); treat as Any so the dict branch is reachable.
    detail: Any = exc.detail
    code: str | None = None
    body_detail: Any

    if isinstance(detail, dict):
        raw_code = detail.get("error_code")
        code = raw_code if isinstance(raw_code, str) else None
        body_detail = detail  # keep shape for existing dict-detail consumers
    elif isinstance(detail, str) and detail:
        body_detail = detail
    else:
        body_detail = (
            _FALLBACK_4XX
            if status_code < HTTPStatus.INTERNAL_SERVER_ERROR
            else _FALLBACK_5XX
        )

    return build_problem_response(
        status_code=status_code,
        detail=body_detail,
        code=code,
        request_id=_request_id(request),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log internal detail; never echo ``str(exc)`` in the body.

    Internal messages go to the logger only; the body never carries them.
    """
    import traceback

    request_id = _request_id(request)
    error_details: dict[str, Any] = {
        "request_id": request_id,
        "url": str(request.url),
        "method": request.method,
        "error": str(exc),
    }
    if get_api_settings().debug:
        error_details["traceback"] = traceback.format_exc()
    logger.exception("unhandled_exception", extra=error_details)

    return build_problem_response(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        detail=_FALLBACK_5XX,
        code="E1002",
        request_id=request_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register the fixed validation / HTTP / catch-all handlers on ``app``."""
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
