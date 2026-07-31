from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from agreement_intelligence_api.agreements.schemas import ErrorResponse

ERROR_MESSAGES = {
    "authentication_required": "Authentication required",
    "resource_not_found": "Resource not found",
    "validation_error": "Request validation failed",
}


def _correlation_id(request: Request) -> str:
    correlation_id = getattr(request.state, "correlation_id", None)
    return str(correlation_id or request.headers.get("X-Correlation-ID") or "")


def _error_payload(request: Request, *, code: str, message: str | None = None) -> dict[str, str]:
    return ErrorResponse(
        code=code,
        message=message or ERROR_MESSAGES.get(code, "Request failed"),
        correlation_id=_correlation_id(request),
    ).model_dump()


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=500,
            content=_error_payload(request, code="http_error"),
        )
    detail = exc.detail
    code = _detail_code(detail) or "http_error"
    if code != "authentication_required":
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=exc.headers,
        )
    message = _detail_message(detail) or ERROR_MESSAGES.get(code)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(request, code=code, message=message),
        headers=exc.headers,
    )


async def request_validation_exception_handler(
    request: Request,
    _: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(request, code="validation_error"),
    )


def _detail_code(detail: Any) -> str | None:
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str):
            return code
    return None


def _detail_message(detail: Any) -> str | None:
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            return message
    if isinstance(detail, str):
        return detail
    return None
