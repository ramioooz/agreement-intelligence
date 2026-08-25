from unittest.mock import Mock

from agreement_intelligence_api.redis_client import atomic_window_consume, consume_quota


def test_consume_quota_sets_window_on_first_request() -> None:
    redis = Mock()
    redis.incr.return_value = 1

    assert consume_quota(redis, "quota:tenant-1", limit=2, window_seconds=60)
    redis.expire.assert_called_once_with("quota:tenant-1", 60)


def test_consume_quota_rejects_over_limit() -> None:
    redis = Mock()
    redis.incr.return_value = 3

    assert not consume_quota(redis, "quota:tenant-1", limit=2, window_seconds=60)


def test_atomic_window_uses_one_redis_script() -> None:
    redis = Mock()
    redis.eval.return_value = [2, 41]

    count, retry_after = atomic_window_consume(
        redis,
        "rate:tenant:user:search",
        limit=3,
        window_seconds=60,
    )

    assert (count, retry_after) == (2, 41)
    redis.eval.assert_called_once()
