from unittest.mock import Mock

from agreement_intelligence_api.redis_client import consume_quota


def test_consume_quota_sets_window_on_first_request() -> None:
    redis = Mock()
    redis.incr.return_value = 1

    assert consume_quota(redis, "quota:tenant-1", limit=2, window_seconds=60)
    redis.expire.assert_called_once_with("quota:tenant-1", 60)


def test_consume_quota_rejects_over_limit() -> None:
    redis = Mock()
    redis.incr.return_value = 3

    assert not consume_quota(redis, "quota:tenant-1", limit=2, window_seconds=60)
