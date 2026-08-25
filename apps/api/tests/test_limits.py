from uuid import uuid4

from agreement_intelligence_api.limits import LimitScope, RateLimitPolicy, reserve_rate_limit
from agreement_intelligence_api.usage import (
    AIUsageLedgerRecord,
    UsageAmount,
    UsageBudget,
    UsageLedgerService,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FakeRedis:
    def __init__(self, result: list[int] | None = None, *, unavailable: bool = False) -> None:
        self.result = result or [1, 60]
        self.unavailable = unavailable
        self.keys: list[str] = []

    def eval(self, _script: str, _key_count: int, *keys_and_args: str) -> object:
        if self.unavailable:
            raise ConnectionError("redis unavailable")
        key = keys_and_args[0]
        self.keys.append(key)
        return self.result


def _scope() -> LimitScope:
    return LimitScope(organization_id=uuid4(), workspace_id=uuid4(), user_id=uuid4())


def test_rate_limit_is_tenant_and_user_scoped() -> None:
    redis = FakeRedis()
    scope = _scope()

    decision = reserve_rate_limit(
        redis,
        scope=scope,
        operation="qa.turn",
        policy=RateLimitPolicy(limit=2, window_seconds=60, expensive=True),
    )

    assert decision.allowed
    assert str(scope.organization_id) in redis.keys[0]
    assert str(scope.user_id) in redis.keys[0]


def test_expensive_operation_fails_closed_when_redis_is_unavailable() -> None:
    decision = reserve_rate_limit(
        FakeRedis(unavailable=True),
        scope=_scope(),
        operation="model.generate",
        policy=RateLimitPolicy(limit=2, window_seconds=60, expensive=True),
    )

    assert not decision.allowed
    assert decision.reason == "limit_service_unavailable"


def test_rate_limit_returns_retry_after() -> None:
    decision = reserve_rate_limit(
        FakeRedis([3, 19]),
        scope=_scope(),
        operation="qa.turn",
        policy=RateLimitPolicy(limit=2, window_seconds=60, expensive=True),
    )

    assert not decision.allowed
    assert decision.reason == "rate_limit_exceeded"
    assert decision.retry_after_seconds == 19


def test_usage_reservation_and_settlement_are_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AIUsageLedgerRecord.metadata.create_all(engine)
    scope = _scope()
    reservation_id = uuid4()
    with Session(engine) as session:
        service = UsageLedgerService(
            session,
            budget=UsageBudget(max_tokens=10_000, max_cost_usd=10),
        )
        first = service.reserve_usage(
            scope=scope,
            operation="model.generate",
            provider="openai",
            configuration_version="gateway.v1",
            estimated=UsageAmount(tokens=100, cost_usd=0.05),
            reservation_id=reservation_id,
        )
        repeated = service.reserve_usage(
            scope=scope,
            operation="model.generate",
            provider="openai",
            configuration_version="gateway.v1",
            estimated=UsageAmount(tokens=100, cost_usd=0.05),
            reservation_id=reservation_id,
        )
        service.settle_usage(
            reservation_id,
            actual=UsageAmount(tokens=80, cost_usd=0.04),
            settlement_key="provider-request-1",
        )
        service.settle_usage(
            reservation_id,
            actual=UsageAmount(tokens=80, cost_usd=0.04),
            settlement_key="provider-request-1",
        )

        rows = session.query(AIUsageLedgerRecord).all()

    assert first.allowed and repeated.allowed
    assert len(rows) == 1
    assert rows[0].status == "settled"
    assert rows[0].actual_tokens == 80


def test_budget_denial_does_not_disclose_usage_values() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AIUsageLedgerRecord.metadata.create_all(engine)
    with Session(engine) as session:
        decision = UsageLedgerService(
            session,
            budget=UsageBudget(max_tokens=10, max_cost_usd=0.01),
        ).reserve_usage(
            scope=_scope(),
            operation="model.generate",
            provider="openai",
            configuration_version="gateway.v1",
            estimated=UsageAmount(tokens=100, cost_usd=1),
        )

    assert not decision.allowed
    assert decision.reason == "budget_exhausted"
    assert decision.retry_after_seconds is None
