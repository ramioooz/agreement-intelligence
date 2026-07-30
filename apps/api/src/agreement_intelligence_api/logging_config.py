import json
import logging
import re
from typing import Any

from agreement_intelligence_api.correlation import get_correlation_id

SENSITIVE_MESSAGE_PATTERN = re.compile(
    r"\b(agreement|bearer|credential|password|secret|token)\b",
    re.IGNORECASE,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "correlation_id": getattr(record, "correlation_id", get_correlation_id()),
            "event": getattr(record, "event", "log"),
            "level": record.levelname,
            "message": _safe_message(record.getMessage()),
            "service": getattr(record, "service", "api"),
        }

        for field in ("method", "path", "status_code"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        return json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("agreement_intelligence.api")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _safe_message(message: str) -> str:
    if SENSITIVE_MESSAGE_PATTERN.search(message):
        return "[redacted]"

    return message
