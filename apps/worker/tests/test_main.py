import asyncio
import signal
from collections.abc import Callable

from pytest import MonkeyPatch


def test_serve_registers_shutdown_signals_and_runs_worker(
    monkeypatch: MonkeyPatch,
) -> None:
    from agreement_intelligence_worker import main as worker_main

    callbacks: dict[signal.Signals, Callable[[], None]] = {}

    class FakeEventLoop:
        def add_signal_handler(
            self,
            shutdown_signal: signal.Signals,
            callback: Callable[[], None],
        ) -> None:
            callbacks[shutdown_signal] = callback

    async def fake_run_worker(stop_event: asyncio.Event) -> None:
        assert set(callbacks) == {signal.SIGINT, signal.SIGTERM}
        assert not stop_event.is_set()

        callbacks[signal.SIGTERM]()

        assert stop_event.is_set()

    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: FakeEventLoop(),
    )
    monkeypatch.setattr(worker_main, "run_worker", fake_run_worker)

    asyncio.run(worker_main.serve())
