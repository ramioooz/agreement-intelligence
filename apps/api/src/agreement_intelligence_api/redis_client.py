"""Redis boundary for ephemeral platform coordination.

Redis is deliberately not used for durable document processing. SQS remains the
source of truth for jobs; this client is limited to cache, quotas, and rate limits.
"""

from __future__ import annotations

import os
from typing import Any

from redis import Redis


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
