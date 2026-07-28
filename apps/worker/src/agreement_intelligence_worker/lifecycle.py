import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("agreement_intelligence.worker")

DEFAULT_HEARTBEAT_PATH = Path("/tmp/agreement-worker-heartbeat")
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0


async def run_worker(
    stop_event: asyncio.Event,
    *,
    heartbeat_path: Path | None = None,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    logger.info(
        "worker started",
        extra={
            "event": "worker.started",
            "service": "worker",
        },
    )

    active_heartbeat_path = heartbeat_path or Path(
        os.environ.get("WORKER_HEARTBEAT_PATH", str(DEFAULT_HEARTBEAT_PATH))
    )

    while not stop_event.is_set():
        active_heartbeat_path.write_text(str(time.time_ns()))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=heartbeat_interval_seconds,
            )

    logger.info(
        "worker stopped",
        extra={
            "event": "worker.stopped",
            "service": "worker",
        },
    )
