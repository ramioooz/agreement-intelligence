from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from agreement_intelligence_worker.agreement_deletion import (
    AgreementDeletion,
    AgreementDeletionProcessor,
    DeletionRetryPolicy,
)


@dataclass
class InMemoryRepository:
    deletion: AgreementDeletion
    state: str = "accepted"
    completed: bool = False
    failed: bool = False

    def claim(
        self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID
    ) -> AgreementDeletion | None:
        if (
            deletion_id != self.deletion.id
            or organization_id != self.deletion.organization_id
            or workspace_id != self.deletion.workspace_id
            or self.state not in {"accepted", "retrying"}
        ):
            return None
        self.state = "processing"
        self.deletion = replace(
            self.deletion,
            attempt_count=self.deletion.attempt_count + 1,
        )
        return self.deletion

    def complete(self, deletion: AgreementDeletion) -> None:
        assert deletion == self.deletion
        self.completed = True
        self.state = "completed"

    def retry(self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime) -> None:
        assert deletion == self.deletion
        assert message == "Agreement deletion cleanup failed"
        assert next_retry_at
        self.state = "retrying"

    def fail(self, deletion: AgreementDeletion, *, message: str) -> None:
        assert deletion == self.deletion
        assert message == "Agreement deletion cleanup failed"
        self.failed = True
        self.state = "failed"


@dataclass
class InMemoryQueue:
    retries: list[tuple[UUID, int]]

    def enqueue_deletion(
        self,
        deletion_id: UUID,
        *,
        agreement_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None:
        del agreement_id, organization_id, workspace_id
        self.retries.append((deletion_id, delay_seconds))


class PartiallyFailingStorage:
    def __init__(self, failing_key: str) -> None:
        self.failing_key = failing_key
        self.failed_once = False
        self.calls: list[str] = []

    def delete(self, key: str) -> None:
        self.calls.append(key)
        if key == self.failing_key and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("temporary S3 failure")


def _deletion() -> AgreementDeletion:
    organization_id = uuid4()
    workspace_id = uuid4()
    base = f"tenants/{organization_id}/workspaces/{workspace_id}"
    return AgreementDeletion(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=uuid4(),
        object_keys=(
            f"{base}/documents/a/original.pdf",
            f"{base}/agreements/a/analysis.json",
        ),
        attempt_count=0,
    )


def test_partial_s3_failure_retries_idempotently_then_records_completion() -> None:
    deletion = _deletion()
    repository = InMemoryRepository(deletion)
    storage = PartiallyFailingStorage(deletion.object_keys[1])
    queue = InMemoryQueue([])
    processor = AgreementDeletionProcessor(repository, storage, queue)

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "retrying"
    assert not repository.completed
    assert queue.retries == [(deletion.id, 2)]

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "completed"
    assert storage.calls == [
        deletion.object_keys[0],
        deletion.object_keys[1],
        deletion.object_keys[0],
        deletion.object_keys[1],
    ]


def test_database_completion_failure_records_failed_instead_of_completed() -> None:
    deletion = _deletion()

    class FailingCompletionRepository(InMemoryRepository):
        def complete(self, deletion: AgreementDeletion) -> None:
            del deletion
            raise RuntimeError("database failure")

    repository = FailingCompletionRepository(deletion)
    storage = PartiallyFailingStorage("never")
    processor = AgreementDeletionProcessor(
        repository,
        storage,
        InMemoryQueue([]),
        retry_policy=DeletionRetryPolicy(max_attempts=1),
    )

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "failed"
    assert repository.failed
