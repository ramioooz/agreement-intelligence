"""Redis boundary for ephemeral platform coordination.

Redis is deliberately not used for durable document processing. SQS remains the
source of truth for jobs; this client is limited to cache, quotas, and rate limits.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from redis import Redis

_ATOMIC_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


class RedisWindowClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...


def redis_from_environment() -> Redis:
    """Create a typed Redis client using the configured ephemeral service."""

    return Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def consume_quota(redis: Redis, key: str, limit: int, window_seconds: int) -> bool:
    """Atomically consume one quota unit, returning whether it is available."""

    current: Any = redis.incr(key)
    if current == 1:
        redis.expire(key, window_seconds)
    return int(current) <= limit


def atomic_window_consume(
    redis: RedisWindowClient, key: str, *, limit: int, window_seconds: int
) -> tuple[int, int]:
    """Consume one distributed fixed-window unit with one atomic Redis script."""

    result = redis.eval(
        _ATOMIC_WINDOW_SCRIPT,
        1,
        key,
        str(window_seconds),
        str(limit),
    )
    if not isinstance(result, list | tuple) or len(result) != 2:
        raise RuntimeError("Redis returned an invalid rate-limit result")
    return int(result[0]), max(int(result[1]), 1)
