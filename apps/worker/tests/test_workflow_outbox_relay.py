import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

from agreement_intelligence_worker.workflow_outbox_relay import (
    WorkflowOutboxRelay,
    run_workflow_outbox_relay,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


class FlakyPublisher:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, event: dict[str, object]) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("queue unavailable")


def test_relay_recovers_transient_failure_and_expired_crash_lease() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event_id = str(uuid4())
    second_event_id = str(uuid4())
    now = datetime(2026, 8, 26, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE review_workflow_outbox (
              id TEXT PRIMARY KEY, workflow_id TEXT, organization_id TEXT, workspace_id TEXT,
              idempotency_key TEXT, delivered_at TEXT, created_at TEXT, attempt_count INTEGER,
              next_attempt_at TEXT, lease_owner TEXT, lease_expires_at TEXT, last_error TEXT
            )
        """)
        )
        connection.execute(
            text("""
            INSERT INTO review_workflow_outbox VALUES
            (:id, :workflow, :organization, :workspace, 'event-key', NULL, :created, 0,
             NULL, 'crashed-relay', :expired, NULL)
        """),
            {
                "id": event_id,
                "workflow": str(uuid4()),
                "organization": str(uuid4()),
                "workspace": str(uuid4()),
                "created": now - timedelta(minutes=2),
                "expired": now - timedelta(minutes=1),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO review_workflow_outbox VALUES
                (:id, :workflow, :organization, :workspace, 'event-key-2', NULL,
                 :created, 0, NULL, NULL, NULL, NULL)
                """
            ),
            {
                "id": second_event_id,
                "workflow": str(uuid4()),
                "organization": str(uuid4()),
                "workspace": str(uuid4()),
                "created": now - timedelta(minutes=1),
            },
        )
    publisher = FlakyPublisher()
    relay = WorkflowOutboxRelay(engine, publisher, owner="replacement-relay")

    assert relay.relay_once(now=now) is False
    with engine.connect() as connection:
        failed = (
            connection.execute(
                text("SELECT * FROM review_workflow_outbox WHERE id = :id"),
                {"id": event_id},
            )
            .mappings()
            .one()
        )
    assert failed["delivered_at"] is None
    assert failed["attempt_count"] == 1
    retry_at = datetime.fromisoformat(failed["next_attempt_at"])

    assert relay.relay_once(now=retry_at + timedelta(seconds=1)) is True
    assert relay.relay_once(now=retry_at + timedelta(seconds=1)) is True
    with engine.connect() as connection:
        recovered = (
            connection.execute(text("SELECT * FROM review_workflow_outbox ORDER BY created_at"))
            .mappings()
            .all()
        )
    assert all(item["delivered_at"] is not None for item in recovered)
    assert all(item["lease_owner"] is None for item in recovered)
    assert publisher.calls == 3
    engine.dispose()


def test_relay_loop_survives_a_transient_database_failure() -> None:
    stop_event = asyncio.Event()

    class FlakyRelay:
        calls = 0

        def relay_once(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                raise OperationalError("SELECT pending", {}, RuntimeError("database restarting"))
            stop_event.set()
            return False

    relay = FlakyRelay()
    asyncio.run(
        run_workflow_outbox_relay(
            stop_event,
            relay,  # type: ignore[arg-type]
            idle_seconds=0,
            database_backoff_base_seconds=0,
        )
    )
    assert relay.calls == 2


def test_relay_loop_keeps_event_loop_responsive_during_blocking_publish() -> None:
    timeline: list[str] = []
    release = Event()
    stop_event = asyncio.Event()

    class BlockingRelay:
        def relay_once(self) -> bool:
            timeline.append("relay-started")
            release.wait(timeout=0.2)
            timeline.append("relay-finished")
            return False

    async def heartbeat() -> None:
        while "relay-started" not in timeline:
            await asyncio.sleep(0)
        timeline.append("heartbeat")
        release.set()
        stop_event.set()

    async def exercise() -> None:
        await asyncio.gather(
            run_workflow_outbox_relay(
                stop_event,
                BlockingRelay(),  # type: ignore[arg-type]
                idle_seconds=0,
            ),
            heartbeat(),
        )

    asyncio.run(exercise())

    assert timeline == ["relay-started", "heartbeat", "relay-finished"]
