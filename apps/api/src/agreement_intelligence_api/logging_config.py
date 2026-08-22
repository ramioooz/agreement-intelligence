import json
import logging
from typing import Any

from agreement_intelligence_platform.privacy import redact_mapping

from agreement_intelligence_api.correlation import get_correlation_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "correlation_id": getattr(record, "correlation_id", get_correlation_id()),
            "event": getattr(record, "event", "log"),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": getattr(record, "service", "api"),
        }

        for field in ("method", "path", "status_code"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        return json.dumps(
            redact_mapping(payload),
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
