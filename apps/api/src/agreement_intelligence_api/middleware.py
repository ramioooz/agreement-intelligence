import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agreement_intelligence_api.correlation import (
    CORRELATION_ID_HEADER,
    reset_correlation_id,
    resolve_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger("agreement_intelligence.api")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = resolve_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)

        try:
            response = await call_next(request)
        finally:
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
