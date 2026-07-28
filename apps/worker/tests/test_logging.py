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
        "event": "worker.started",
        "level": "INFO",
        "message": "worker started",
        "service": "worker",
    }
