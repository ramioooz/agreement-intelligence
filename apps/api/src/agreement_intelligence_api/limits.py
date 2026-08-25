from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from agreement_intelligence_api.redis_client import RedisWindowClient, atomic_window_consume


@dataclass(frozen=True)
class LimitScope:
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int
    expensive: bool


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason: str
    retry_after_seconds: int | None = None
    reservation_id: UUID | None = None


_fallback_lock = Lock()
_fallback_windows: dict[str, tuple[float, int]] = {}


def reserve_rate_limit(
    redis: RedisWindowClient,
    *,
    scope: LimitScope,
    operation: str,
    policy: RateLimitPolicy,
) -> LimitDecision:
    """Reserve a scoped request unit without exposing counters to callers."""

    key = f"rate:{scope.organization_id}:{scope.workspace_id}:{scope.user_id}:{operation}"
    try:
        count, ttl = atomic_window_consume(
            redis,
            key,
            limit=policy.limit,
            window_seconds=policy.window_seconds,
        )
    except (RedisError, ConnectionError, OSError, RuntimeError):
        if policy.expensive:
            return LimitDecision(False, "limit_service_unavailable", retry_after_seconds=1)
        return _reserve_local_fallback(key, policy)
    if count > policy.limit:
        return LimitDecision(False, "rate_limit_exceeded", retry_after_seconds=ttl)
    return LimitDecision(True, "allowed")


def enforce_rate_limit(
    *, scope: LimitScope, operation: str, policy: RateLimitPolicy
) -> LimitDecision:
    from agreement_intelligence_api.redis_client import redis_from_environment

    decision = reserve_rate_limit(
        redis_from_environment(), scope=scope, operation=operation, policy=policy
    )
    if decision.allowed:
        return decision
    headers = (
        {"Retry-After": str(decision.retry_after_seconds)}
        if decision.retry_after_seconds is not None
        else None
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": decision.reason},
        headers=headers,
    )


def _reserve_local_fallback(key: str, policy: RateLimitPolicy) -> LimitDecision:
    now = monotonic()
    conservative_limit = max(1, min(policy.limit, 10))
    with _fallback_lock:
        started_at, count = _fallback_windows.get(key, (now, 0))
        if now - started_at >= policy.window_seconds:
            started_at, count = now, 0
        count += 1
        _fallback_windows[key] = (started_at, count)
    if count > conservative_limit:
        retry_after = max(1, round(policy.window_seconds - (now - started_at)))
        return LimitDecision(False, "rate_limit_exceeded", retry_after_seconds=retry_after)
    return LimitDecision(True, "allowed_degraded")
