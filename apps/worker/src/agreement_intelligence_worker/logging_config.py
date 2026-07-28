import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "event": getattr(record, "event", "log"),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": getattr(record, "service", "worker"),
        }

        return json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("agreement_intelligence.worker")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
