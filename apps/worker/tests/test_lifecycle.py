import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agreement_intelligence_worker.lifecycle import run_worker
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    JobProcessor,
    ProcessingJob,
    ProcessingMessage,
)
from pytest import LogCaptureFixture


def test_worker_waits_until_stop_is_requested(
    caplog: LogCaptureFixture,
) -> None:
    async def exercise() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_worker(stop_event, correlation_id="worker-test-correlation-id")
        )

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
    assert {getattr(record, "correlation_id", None) for record in caplog.records} == {
        "worker-test-correlation-id"
    }


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


def test_worker_lifecycle_consumes_a_processing_message(tmp_path: Path) -> None:
    @dataclass
    class Repository:
        job: ProcessingJob
        artifact: CompletedArtifact | None = None

        def claim(
            self,
            job_id: UUID,
            *,
            organization_id: UUID | None = None,
            workspace_id: UUID | None = None,
        ) -> ProcessingJob | None:
            del organization_id, workspace_id
            if self.job.id != job_id or self.job.state != "queued":
                return None
            self.job = replace(
                self.job,
                state="processing",
                attempt_count=self.job.attempt_count + 1,
                processing_started_at=datetime.now(UTC),
            )
            return self.job

        def complete(
            self,
            job_id: UUID,
            artifact: CompletedArtifact,
            *,
            organization_id: UUID | None = None,
            workspace_id: UUID | None = None,
        ) -> None:
            del organization_id, workspace_id
            assert self.job.id == job_id
            self.artifact = artifact
            self.job = replace(self.job, state="completed", completed_at=datetime.now(UTC))

        def requeue(
            self,
            job_id: UUID,
            *,
            category: str,
            message: str,
            next_retry_at: datetime,
            organization_id: UUID | None = None,
            workspace_id: UUID | None = None,
        ) -> None:
            del job_id, category, message, next_retry_at, organization_id, workspace_id
            raise AssertionError("unexpected retry")

        def fail(
            self,
            job_id: UUID,
            *,
            category: str,
            message: str,
            organization_id: UUID | None = None,
            workspace_id: UUID | None = None,
        ) -> None:
            del job_id, category, message, organization_id, workspace_id
            raise AssertionError("unexpected failure")

    class Queue:
        def enqueue(
            self,
            job_id: UUID,
            *,
            organization_id: UUID,
            workspace_id: UUID,
            delay_seconds: int,
        ) -> None:
            del job_id, organization_id, workspace_id, delay_seconds
            raise AssertionError("unexpected retry publish")

    class Processor:
        def process(self, job: ProcessingJob) -> CompletedArtifact:
            return CompletedArtifact(job_id=job.id, key=f"checkpoints/{job.id}/placeholder.json")

    class OneMessageReceiver:
        def __init__(self, job_id: UUID, stop_event: asyncio.Event) -> None:
            self._messages = [ProcessingMessage(job_id=job_id, receipt_handle="receipt-1")]
            self._stop_event = stop_event
            self.acked: list[str] = []

        async def receive(self) -> ProcessingMessage | None:
            if self._messages:
                return self._messages.pop(0)
            return None

        async def ack(self, message: ProcessingMessage) -> None:
            self.acked.append(message.receipt_handle)
            self._stop_event.set()

    async def exercise() -> None:
        job = ProcessingJob(
            id=uuid4(),
            agreement_id=uuid4(),
            state="queued",
            attempt_count=0,
            organization_id=uuid4(),
            workspace_id=uuid4(),
        )
        repository = Repository(job=job)
        stop_event = asyncio.Event()
        receiver = OneMessageReceiver(job.id, stop_event)
        job_processor = JobProcessor(repository, Queue(), Processor())

        await asyncio.wait_for(
            run_worker(
                stop_event,
                heartbeat_path=tmp_path / "worker-heartbeat",
                heartbeat_interval_seconds=0.01,
                message_receiver=receiver,
                job_processor=job_processor,
            ),
            timeout=1,
        )

        assert repository.job.state == "completed"
        assert repository.artifact == CompletedArtifact(
            job_id=job.id, key=f"checkpoints/{job.id}/placeholder.json"
        )
        assert receiver.acked == ["receipt-1"]

    asyncio.run(exercise())
