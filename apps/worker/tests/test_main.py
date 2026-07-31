import asyncio
import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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


def test_serve_composes_processing_runtime_when_queue_is_configured(
    monkeypatch: MonkeyPatch,
) -> None:
    from agreement_intelligence_worker import main as worker_main

    @dataclass
    class Runtime:
        receiver: object
        processor: object

    runtime = Runtime(receiver=object(), processor=object())
    captured: dict[str, object] = {}

    class FakeEventLoop:
        def add_signal_handler(
            self,
            shutdown_signal: signal.Signals,
            callback: Callable[[], None],
        ) -> None:
            pass

    async def fake_run_worker(
        stop_event: asyncio.Event,
        **kwargs: Any,
    ) -> None:
        captured.update(kwargs)
        stop_event.set()

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SQS_PROCESSING_QUEUE", "https://sqs.example/processing.fifo")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///worker.db")
    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: FakeEventLoop(),
    )
    monkeypatch.setattr(worker_main, "run_worker", fake_run_worker)
    monkeypatch.setattr(worker_main, "processing_runtime_from_environment", lambda: runtime)

    asyncio.run(worker_main.serve())

    assert captured["message_receiver"] is runtime.receiver
    assert captured["job_processor"] is runtime.processor


def test_serve_keeps_heartbeat_only_when_queue_is_not_configured(
    monkeypatch: MonkeyPatch,
) -> None:
    from agreement_intelligence_worker import main as worker_main

    captured: dict[str, object] = {}

    class FakeEventLoop:
        def add_signal_handler(
            self,
            shutdown_signal: signal.Signals,
            callback: Callable[[], None],
        ) -> None:
            pass

    async def fake_run_worker(
        stop_event: asyncio.Event,
        **kwargs: Any,
    ) -> None:
        captured.update(kwargs)
        stop_event.set()

    monkeypatch.delenv("SQS_PROCESSING_QUEUE", raising=False)
    monkeypatch.setattr(
        asyncio,
        "get_running_loop",
        lambda: FakeEventLoop(),
    )
    monkeypatch.setattr(worker_main, "run_worker", fake_run_worker)

    asyncio.run(worker_main.serve())

    assert captured == {}
