import asyncio
import signal

from agreement_intelligence_worker.lifecycle import run_worker
from agreement_intelligence_worker.logging_config import configure_logging


async def serve() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    await run_worker(stop_event)


def main() -> None:
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
