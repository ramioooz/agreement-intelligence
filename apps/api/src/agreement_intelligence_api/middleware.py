import logging
import os

from agreement_intelligence_platform.document_safety import MAX_DOCUMENT_COMPRESSED_BYTES
from agreement_intelligence_platform.observability import (
    extract_trace_context,
    safe_span_attributes,
)
from agreement_intelligence_platform.telemetry import operation_span
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.context import attach, detach
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agreement_intelligence_api.correlation import (
    CORRELATION_ID_HEADER,
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger("agreement_intelligence.api")

DEFAULT_MAX_UPLOAD_BYTES = MAX_DOCUMENT_COMPRESSED_BYTES


class DocumentUploadBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _is_document_upload(scope):
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length is None:
                await JSONResponse(
                    status_code=411,
                    content={"detail": "A Content-Length header is required for document uploads."},
                )(scope, receive, send)
                return
            try:
                declared_length = int(content_length.decode("ascii"))
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={"detail": "Content-Length must be an integer."},
                )(scope, receive, send)
                return
            max_bytes = _configured_max_upload_bytes()
            if declared_length > max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "The request body exceeds the maximum allowed size."},
                )(scope, receive, send)
                return
            received_bytes = 0
            body_messages: list[Message] = []

            while True:
                message = await receive()
                if message["type"] == "http.request":
                    body = message.get("body", b"")
                    if isinstance(body, bytes):
                        received_bytes += len(body)
                    if received_bytes > max_bytes:
                        await JSONResponse(
                            status_code=413,
                            content={
                                "detail": "The request body exceeds the maximum allowed size."
                            },
                        )(scope, receive, send)
                        return
                    body_messages.append(message)
                    if not message.get("more_body", False):
                        break
                elif message["type"] == "http.disconnect":
                    return

            async def replay_receive() -> Message:
                if body_messages:
                    return body_messages.pop(0)
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay_receive, send)
            return

        await self.app(scope, receive, send)


def _is_document_upload(scope: Scope) -> bool:
    if scope["type"] != "http" or scope["method"] != "POST":
        return False
    path = scope["path"]
    if path == "/documents":
        return True
    segments = path.strip("/").split("/")
    return len(segments) == 3 and segments[0] == "agreements" and segments[2] == "versions"


def _configured_max_upload_bytes() -> int:
    configured = os.environ.get("MAX_DOCUMENT_UPLOAD_BYTES")
    if configured is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(configured)
    except ValueError as error:
        raise RuntimeError("MAX_DOCUMENT_UPLOAD_BYTES must be an integer.") from error
    if value <= 0:
        raise RuntimeError("MAX_DOCUMENT_UPLOAD_BYTES must be positive.")
    return min(value, MAX_DOCUMENT_COMPRESSED_BYTES)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = resolve_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        trace_token = attach(extract_trace_context(request.headers))

        try:
            with operation_span(
                "agreement-intelligence.api",
                "http.request",
                safe_span_attributes(
                    {"operation": "http.request", "outcome": "success", "method": request.method}
                ),
            ):
                response = await call_next(request)
                span_context = trace.get_current_span().get_span_context()
                if span_context.is_valid:
                    response.headers["X-Trace-ID"] = f"{span_context.trace_id:032x}"
        finally:
            detach(trace_token)
            reset_correlation_id(token)

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        logger.info(
            "request completed",
            extra={
                "correlation_id": correlation_id,
                "event": "http.request.completed",
                "method": request.method,
                "path": request.url.path,
                "service": "api",
                "status_code": response.status_code,
            },
        )
        return response
