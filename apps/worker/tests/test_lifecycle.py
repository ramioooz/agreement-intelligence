import asyncio
import logging
from pathlib import Path

from agreement_intelligence_worker.lifecycle import run_worker
from pytest import LogCaptureFixture


def test_worker_waits_until_stop_is_requested(
    caplog: LogCaptureFixture,
) -> None:
    async def exercise() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(run_worker(stop_event))

        await asyncio.sleep(0)
        assert not task.done()

        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level(
        logging.INFO,
        logger="agreement_intelligence.worker",
    ):
        asyncio.run(exercise())

    events = [getattr(record, "event", None) for record in caplog.records]
    assert events == ["worker.started", "worker.stopped"]


def test_worker_refreshes_its_liveness_heartbeat(tmp_path: Path) -> None:
    async def exercise() -> None:
        stop_event = asyncio.Event()
        heartbeat_path = tmp_path / "worker-heartbeat"
        task = asyncio.create_task(
            run_worker(
                stop_event,
                heartbeat_path=heartbeat_path,
                heartbeat_interval_seconds=0.01,
            )
        )

        for _ in range(100):
            if heartbeat_path.exists():
                break
            await asyncio.sleep(0)

        assert heartbeat_path.exists()
        first_heartbeat = heartbeat_path.read_text()

        for _ in range(100):
            if heartbeat_path.read_text() != first_heartbeat:
                break
            await asyncio.sleep(0.002)

        assert heartbeat_path.read_text() != first_heartbeat

        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(exercise())
