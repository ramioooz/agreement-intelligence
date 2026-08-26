import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable
from pathlib import Path
from typing import Any
from uuid import uuid4

from agreement_intelligence_worker.processing import (
    DeletionMessageProcessor,
    JobProcessor,
    ProcessingMessageReceiver,
    run_processing_loop,
)

logger = logging.getLogger("agreement_intelligence.worker")

DEFAULT_HEARTBEAT_PATH = Path("/tmp/agreement-worker-heartbeat")
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0


async def run_worker(
    stop_event: asyncio.Event,
    *,
    correlation_id: str | None = None,
    heartbeat_path: Path | None = None,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    message_receiver: ProcessingMessageReceiver | None = None,
    job_processor: JobProcessor | None = None,
    deletion_processor: DeletionMessageProcessor | None = None,
    background_tasks: tuple[Awaitable[None], ...] = (),
) -> None:
    lifecycle_correlation_id = correlation_id or os.environ.get(
        "WORKER_CORRELATION_ID",
        f"worker-{uuid4()}",
    )
    logger.info(
        "worker started",
        extra={
            "correlation_id": lifecycle_correlation_id,
            "event": "worker.started",
            "service": "worker",
        },
    )

    active_heartbeat_path = heartbeat_path or Path(
        os.environ.get("WORKER_HEARTBEAT_PATH", str(DEFAULT_HEARTBEAT_PATH))
    )

    processing_task: asyncio.Task[None] | None = None
    if message_receiver is not None and job_processor is not None:
        processing_task = asyncio.create_task(
            run_processing_loop(
                stop_event,
                receiver=message_receiver,
                processor=job_processor,
                deletion_processor=deletion_processor,
                idle_sleep_seconds=heartbeat_interval_seconds,
            )
        )
    supplemental_tasks: list[asyncio.Future[None]] = [
        asyncio.ensure_future(task) for task in background_tasks
    ]

    try:
        while not stop_event.is_set():
            active_heartbeat_path.write_text(str(time.time_ns()))
            stop_task = asyncio.create_task(stop_event.wait())
            watched_tasks = [
                task for task in (processing_task, *supplemental_tasks) if task is not None
            ]
            waiters: list[asyncio.Future[Any]] = [stop_task, *watched_tasks]
            done, _ = await asyncio.wait(
                waiters,
                timeout=heartbeat_interval_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task not in done:
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task
            if stop_task in done and stop_event.is_set():
                for task in watched_tasks:
                    if task in done:
                        await task
                break
            for task in watched_tasks:
                if task in done:
                    await task
                    raise RuntimeError("worker background task stopped unexpectedly")
    finally:
        if processing_task is not None:
            processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await processing_task
        for task in supplemental_tasks:
            task.cancel()
        for task in supplemental_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    logger.info(
        "worker stopped",
        extra={
            "correlation_id": lifecycle_correlation_id,
            "event": "worker.stopped",
            "service": "worker",
        },
    )
