from contextvars import ContextVar, Token
from uuid import UUID, uuid4

CORRELATION_ID_HEADER = "X-Correlation-ID"
_correlation_id: ContextVar[str] = ContextVar(
    "correlation_id",
    default="unavailable",
)


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> Token[str]:
    return _correlation_id.set(correlation_id)


def reset_correlation_id(token: Token[str]) -> None:
    _correlation_id.reset(token)


def resolve_correlation_id(value: str | None) -> str:
    if value and _is_valid_correlation_id(value):
        return value

    return str(uuid4())


def _is_valid_correlation_id(value: str) -> bool:
    try:
        parsed = UUID(value)
    except ValueError:
        return False

    return parsed.version == 4 and str(parsed) == value
