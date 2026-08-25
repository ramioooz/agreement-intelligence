from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.limits import LimitDecision, LimitScope


class AIUsageLedgerRecord(Base):
    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        Index("ix_ai_usage_ledger_scope_created", "organization_id", "workspace_id", "created_at"),
    )

    reservation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operation: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(64))
    configuration_version: Mapped[str] = mapped_column(String(128))
    estimated_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float] = mapped_column(Float)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    settlement_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True)
class UsageAmount:
    tokens: int
    cost_usd: float


@dataclass(frozen=True)
class UsageBudget:
    max_tokens: int
    max_cost_usd: float

    @classmethod
    def from_environment(cls) -> UsageBudget:
        return cls(
            max_tokens=_positive_int("AI_MONTHLY_TOKEN_BUDGET", 1_000_000),
            max_cost_usd=_positive_float("AI_MONTHLY_COST_BUDGET_USD", 25.0),
        )


class UsageLedgerService:
    def __init__(self, session: Session, *, budget: UsageBudget | None = None) -> None:
        self._session = session
        self._budget = budget or UsageBudget.from_environment()

    def reserve_usage(
        self,
        *,
        scope: LimitScope,
        operation: str,
        provider: str,
        configuration_version: str,
        estimated: UsageAmount,
        reservation_id: UUID | None = None,
    ) -> LimitDecision:
        resolved_id = reservation_id or uuid4()
        existing = self._session.get(AIUsageLedgerRecord, resolved_id)
        if existing is not None:
            same_request = (
                existing.organization_id == scope.organization_id
                and existing.workspace_id == scope.workspace_id
                and existing.user_id == scope.user_id
                and existing.operation == operation
            )
            return LimitDecision(
                same_request,
                "allowed" if same_request else "reservation_conflict",
                reservation_id=resolved_id,
            )

        token_total, cost_total = self._current_usage(scope.organization_id)
        if token_total + estimated.tokens > self._budget.max_tokens or cost_total + Decimal(
            str(estimated.cost_usd)
        ) > Decimal(str(self._budget.max_cost_usd)):
            return LimitDecision(False, "budget_exhausted")

        self._session.add(
            AIUsageLedgerRecord(
                reservation_id=resolved_id,
                organization_id=scope.organization_id,
                workspace_id=scope.workspace_id,
                user_id=scope.user_id,
                operation=operation,
                provider=provider,
                configuration_version=configuration_version,
                estimated_tokens=estimated.tokens,
                estimated_cost_usd=estimated.cost_usd,
                actual_tokens=None,
                actual_cost_usd=None,
                status="reserved",
                settlement_key=None,
            )
        )
        self._session.flush()
        return LimitDecision(True, "allowed", reservation_id=resolved_id)

    def settle_usage(
        self,
        reservation_id: UUID,
        *,
        actual: UsageAmount,
        settlement_key: str,
    ) -> None:
        record = self._session.get(AIUsageLedgerRecord, reservation_id)
        if record is None:
            raise LookupError("usage reservation is unavailable")
        if record.status == "settled":
            if record.settlement_key != settlement_key:
                raise ValueError("usage reservation was settled by another provider request")
            return
        record.actual_tokens = actual.tokens
        record.actual_cost_usd = actual.cost_usd
        record.status = "settled"
        record.settlement_key = settlement_key
        record.settled_at = datetime.now(UTC)
        self._session.flush()

    def cancel_usage(self, reservation_id: UUID) -> None:
        record = self._session.get(AIUsageLedgerRecord, reservation_id)
        if record is None or record.status == "cancelled":
            return
        if record.status == "settled":
            raise ValueError("settled usage cannot be cancelled")
        record.status = "cancelled"
        self._session.flush()

    def _current_usage(self, organization_id: UUID) -> tuple[int, Decimal]:
        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = self._session.execute(
            select(
                AIUsageLedgerRecord.actual_tokens,
                AIUsageLedgerRecord.actual_cost_usd,
                AIUsageLedgerRecord.estimated_tokens,
                AIUsageLedgerRecord.estimated_cost_usd,
            ).where(
                AIUsageLedgerRecord.organization_id == organization_id,
                AIUsageLedgerRecord.created_at >= month_start,
                AIUsageLedgerRecord.status.in_(("reserved", "settled")),
            )
        )
        tokens = 0
        cost = Decimal("0")
        for actual_tokens, actual_cost, estimated_tokens, estimated_cost in rows:
            tokens += actual_tokens if actual_tokens is not None else estimated_tokens
            cost += Decimal(str(actual_cost if actual_cost is not None else estimated_cost))
        return tokens, cost


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value
