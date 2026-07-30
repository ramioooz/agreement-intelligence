import json
import logging

from agreement_intelligence_api.logging_config import JsonFormatter, configure_logging
from agreement_intelligence_api.main import app
from fastapi.testclient import TestClient
from pytest import CaptureFixture


def test_api_request_log_includes_correlation_id(
    capsys: CaptureFixture[str],
) -> None:
    correlation_id = "123e4567-e89b-42d3-a456-426614174000"
    logging.getLogger("agreement_intelligence.api").handlers.clear()
    configure_logging()

    response = TestClient(app).get(
        "/health/live",
        headers={"X-Correlation-ID": correlation_id},
    )
    captured = capsys.readouterr()

    assert response.status_code == 200
    logs = [json.loads(line) for line in captured.err.splitlines()]
    assert {
        "correlation_id": correlation_id,
        "event": "http.request.completed",
        "level": "INFO",
        "message": "request completed",
        "method": "GET",
        "path": "/health/live",
        "service": "api",
        "status_code": 200,
    } in logs


def test_api_structured_logs_do_not_emit_sensitive_fields() -> None:
    record = logging.LogRecord(
        name="agreement_intelligence.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request included bearer token and full agreement text",
        args=(),
        exc_info=None,
    )
    record.event = "http.request.completed"
    record.service = "api"
    record.correlation_id = "safe-correlation-id"
    record.password = "super-secret"
    record.access_token = "token-value"
    record.agreement_text = "Confidential agreement content"

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "correlation_id": "safe-correlation-id",
        "event": "http.request.completed",
        "level": "INFO",
        "message": "[redacted]",
        "service": "api",
    }
