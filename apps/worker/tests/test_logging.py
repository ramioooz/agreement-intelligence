import json
import logging

from agreement_intelligence_worker.logging_config import JsonFormatter
from pytest import CaptureFixture


def test_json_formatter_preserves_lifecycle_fields() -> None:
    record = logging.LogRecord(
        name="agreement_intelligence.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="worker started",
        args=(),
        exc_info=None,
    )
    record.event = "worker.started"
    record.service = "worker"

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "correlation_id": "unavailable",
        "event": "worker.started",
        "level": "INFO",
        "message": "worker started",
        "service": "worker",
    }


def test_configure_logging_writes_one_json_line_to_stderr(
    capsys: CaptureFixture[str],
) -> None:
    from agreement_intelligence_worker.logging_config import configure_logging

    logger = logging.getLogger("agreement_intelligence.worker")
    original_handlers = logger.handlers.copy()
    original_level = logger.level
    original_propagate = logger.propagate

    try:
        configure_logging()
        logger.info(
            "worker started",
            extra={
                "correlation_id": "worker-lifecycle-id",
                "event": "worker.started",
                "service": "worker",
            },
        )
        captured = capsys.readouterr()
    finally:
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert json.loads(captured.err) == {
        "correlation_id": "worker-lifecycle-id",
        "event": "worker.started",
        "level": "INFO",
        "message": "worker started",
        "service": "worker",
    }


def test_worker_structured_logs_do_not_emit_sensitive_fields() -> None:
    record = logging.LogRecord(
        name="agreement_intelligence.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="worker saw password token and agreement contents",
        args=(),
        exc_info=None,
    )
    record.event = "worker.job.received"
    record.service = "worker"
    record.correlation_id = "job-correlation-id"
    record.password = "super-secret"
    record.refresh_token = "token-value"
    record.agreement_text = "Confidential agreement body"

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "correlation_id": "job-correlation-id",
        "event": "worker.job.received",
        "level": "INFO",
        "message": "[redacted]",
        "service": "worker",
    }


def test_worker_structured_logs_redact_email_addresses_in_messages() -> None:
    record = logging.LogRecord(
        name="agreement_intelligence.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job completed for private.person@example.test",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "[redacted]"
