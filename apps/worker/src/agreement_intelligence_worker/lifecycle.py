import asyncio
import logging

logger = logging.getLogger("agreement_intelligence.worker")


async def run_worker(stop_event: asyncio.Event) -> None:
    logger.info(
        "worker started",
        extra={
            "event": "worker.started",
            "service": "worker",
        },
    )

    await stop_event.wait()

    logger.info(
        "worker stopped",
        extra={
            "event": "worker.stopped",
            "service": "worker",
        },
    )
