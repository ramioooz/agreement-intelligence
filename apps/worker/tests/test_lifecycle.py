import asyncio
import logging

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
