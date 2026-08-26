from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agreement_intelligence_worker.agreement_deletion import (
    AgreementDeletion,
    AgreementDeletionObject,
    AgreementDeletionOutboxSweeper,
    AgreementDeletionProcessor,
    ClaimedDeletionOutbox,
    DeletionRetryPolicy,
)
from pytest import raises


@dataclass
class InMemoryRepository:
    deletion: AgreementDeletion
    objects: list[AgreementDeletionObject]
    state: str = "accepted"
    completed: bool = False
    failed: bool = False
    shared_keys: frozenset[str] = frozenset()
    completion_error: Exception | None = None
    database_retry_error: Exception | None = None
    next_retry_at: datetime | None = None
    failure_category: str | None = None

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
            claim_token=uuid4(),
        )
        return self.deletion

    def pending_objects(self, deletion: AgreementDeletion) -> list[AgreementDeletionObject]:
        assert deletion == self.deletion
        return [item for item in self.objects if item.state == "pending"]

    def delete_source_if_unreferenced(
        self,
        deletion: AgreementDeletion,
        item: AgreementDeletionObject,
        delete_object: object,
    ) -> None:
        assert deletion == self.deletion
        if item.object_key in self.shared_keys:
            self._set_object_state(item, "preserved")
            return
        delete_object(item.object_key)  # type: ignore[operator]
        self._set_object_state(item, "deleted")

    def mark_deleted(self, deletion: AgreementDeletion, item: AgreementDeletionObject) -> None:
        assert deletion == self.deletion
        self._set_object_state(item, "deleted")

    def retry(
        self, deletion: AgreementDeletion, *, object_id: UUID, message: str, next_retry_at: datetime
    ) -> None:
        assert deletion == self.deletion
        assert any(item.id == object_id for item in self.objects)
        assert message == "Agreement object cleanup failed"
        self.state = "retrying"
        self.next_retry_at = next_retry_at

    def fail(self, deletion: AgreementDeletion, *, object_id: UUID, message: str) -> None:
        assert deletion == self.deletion
        assert any(item.id == object_id for item in self.objects)
        assert message == "Agreement object cleanup failed"
        self.failed = True
        self.state = "failed"

    def complete_and_purge(self, deletion: AgreementDeletion) -> None:
        assert deletion == self.deletion
        if self.completion_error is not None:
            raise self.completion_error
        assert all(item.state in {"deleted", "preserved"} for item in self.objects)
        self.completed = True
        self.state = "completed"

    def retry_database_cleanup(
        self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime
    ) -> None:
        assert deletion == self.deletion
        assert message == "Agreement database cleanup failed"
        if self.database_retry_error is not None:
            raise self.database_retry_error
        self.state = "retrying"
        self.failure_category = "database_cleanup"
        self.next_retry_at = next_retry_at

    def fail_database_cleanup(self, deletion: AgreementDeletion, *, message: str) -> None:
        assert deletion == self.deletion
        assert message == "Agreement database cleanup failed"
        self.state = "failed"
        self.failed = True
        self.failure_category = "database_cleanup"

    def _set_object_state(self, item: AgreementDeletionObject, state: str) -> None:
        self.objects = [
            replace(value, state=state) if value.id == item.id else value for value in self.objects
        ]


class RecordingStorage:
    def __init__(self, failing_key: str | None = None) -> None:
        self.failing_key = failing_key
        self.failed_once = False
        self.calls: list[str] = []

    def delete(self, key: str) -> None:
        self.calls.append(key)
        if key == self.failing_key and not self.failed_once:
            self.failed_once = True
            raise RuntimeError("temporary S3 failure")


def _deletion() -> tuple[AgreementDeletion, list[AgreementDeletionObject]]:
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    deletion = AgreementDeletion(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        attempt_count=0,
        claim_token=uuid4(),
    )
    base = f"tenants/{organization_id}/workspaces/{workspace_id}"
    objects = [
        AgreementDeletionObject(
            id=uuid4(),
            category="source",
            object_key=f"{base}/documents/{'a' * 64}/original.pdf",
            state="pending",
        ),
        AgreementDeletionObject(
            id=uuid4(),
            category="analysis",
            object_key=(
                f"{base}/agreements/{agreement_id}/analysis/{'a' * 64}/document-analysis.v1.json"
            ),
            state="pending",
        ),
        AgreementDeletionObject(
            id=uuid4(),
            category="comparison",
            object_key=f"comparisons/{uuid4()}/version-comparison.v1.json",
            state="pending",
        ),
        AgreementDeletionObject(
            id=uuid4(),
            category="review_manifest",
            object_key=(
                f"reviews/{organization_id}/{workspace_id}/{uuid4()}/final-package/manifest.json"
            ),
            state="pending",
        ),
    ]
    return deletion, objects


def test_real_object_formats_delete_and_shared_source_is_rechecked_at_cleanup() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(
        deletion,
        objects,
        shared_keys=frozenset({objects[0].object_key}),
    )
    storage = RecordingStorage()

    AgreementDeletionProcessor(repository, storage).handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.completed
    assert repository.objects[0].state == "preserved"
    assert storage.calls == [item.object_key for item in objects[1:]]


def test_partial_s3_failure_persists_due_retry_then_completes_idempotently() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(deletion, objects)
    storage = RecordingStorage(failing_key=objects[1].object_key)
    processor = AgreementDeletionProcessor(repository, storage)

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "retrying"
    assert repository.next_retry_at is not None
    assert not repository.completed

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "completed"
    assert storage.calls.count(objects[0].object_key) == 1
    assert storage.calls.count(objects[1].object_key) == 2


def test_database_completion_failure_persists_retry_and_reopens_delivery() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(
        deletion,
        objects,
        completion_error=RuntimeError("database unavailable"),
    )
    processor = AgreementDeletionProcessor(
        repository,
        RecordingStorage(),
        retry_policy=DeletionRetryPolicy(max_attempts=2),
    )

    processor.handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "retrying"
    assert repository.failure_category == "database_cleanup"
    assert repository.next_retry_at is not None
    assert not repository.failed
    assert not repository.completed


def test_database_completion_exhaustion_records_visible_terminal_failure() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(
        deletion,
        objects,
        completion_error=RuntimeError("database unavailable"),
    )

    AgreementDeletionProcessor(
        repository,
        RecordingStorage(),
        retry_policy=DeletionRetryPolicy(max_attempts=1),
    ).handle(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert repository.state == "failed"
    assert repository.failure_category == "database_cleanup"
    assert repository.failed
    assert not repository.completed


def test_total_database_outage_keeps_delivery_unacknowledged() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(
        deletion,
        objects,
        completion_error=RuntimeError("database unavailable"),
        database_retry_error=RuntimeError("retry persistence unavailable"),
    )

    with raises(RuntimeError, match="retry persistence unavailable"):
        AgreementDeletionProcessor(repository, RecordingStorage()).handle(
            deletion.id,
            organization_id=deletion.organization_id,
            workspace_id=deletion.workspace_id,
        )

    assert repository.state == "processing"


def test_duplicate_delivery_does_not_claim_an_active_lease() -> None:
    deletion, objects = _deletion()
    repository = InMemoryRepository(deletion, objects)
    claimed = repository.claim(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )
    assert claimed is not None

    duplicate = repository.claim(
        deletion.id,
        organization_id=deletion.organization_id,
        workspace_id=deletion.workspace_id,
    )

    assert duplicate is None


def test_autonomous_outbox_sweeper_traverses_tenants_and_releases_failures() -> None:
    first = ClaimedDeletionOutbox(
        id=uuid4(),
        deletion_id=uuid4(),
        agreement_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        lease_token=uuid4(),
    )
    second = replace(
        first,
        id=uuid4(),
        deletion_id=uuid4(),
        organization_id=uuid4(),
        lease_token=uuid4(),
    )

    class OutboxRepository:
        def __init__(self) -> None:
            self.messages = {first.organization_id: first, second.organization_id: second}
            self.delivered: list[UUID] = []
            self.released: list[UUID] = []
            self.recovered: list[UUID] = []

        def organization_ids(self) -> list[UUID]:
            return list(self.messages)

        def recover_stale_deletions(self, organization_id: UUID) -> int:
            self.recovered.append(organization_id)
            return 0

        def claim_due_outbox(self, organization_id: UUID) -> ClaimedDeletionOutbox | None:
            return self.messages.pop(organization_id, None)

        def mark_outbox_delivered(self, message: ClaimedDeletionOutbox) -> None:
            self.delivered.append(message.id)

        def release_outbox(
            self, message: ClaimedDeletionOutbox, *, next_attempt_at: datetime
        ) -> None:
            assert next_attempt_at > datetime.now(UTC)
            self.released.append(message.id)

    class Queue:
        def __init__(self) -> None:
            self.calls: list[UUID] = []

        def enqueue_deletion(self, deletion_id: UUID, **_: object) -> None:
            self.calls.append(deletion_id)
            if deletion_id == second.deletion_id:
                raise RuntimeError("queue unavailable")

    repository = OutboxRepository()
    queue = Queue()

    delivered = AgreementDeletionOutboxSweeper(repository, queue).sweep_once()

    assert delivered == 1
    assert set(repository.recovered) == {first.organization_id, second.organization_id}
    assert repository.delivered == [first.id]
    assert repository.released == [second.id]
