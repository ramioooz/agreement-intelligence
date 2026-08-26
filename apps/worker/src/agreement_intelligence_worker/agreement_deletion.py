from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    insert,
    select,
    text,
    update,
)

deletion_metadata = MetaData()
deletion_requests = Table(
    "agreement_deletion_requests",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("actor_id", Uuid(as_uuid=True), nullable=False),
    Column("title", String(500), nullable=False),
    Column("agreement_type", String(100), nullable=False),
    Column("file_checksums", JSON, nullable=False),
    Column("state", String(32), nullable=False),
    Column("object_keys", JSON, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("failure_category", String(64), nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
deletion_audit_events = Table(
    "agreement_deletion_audit_events",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("title", String(500), nullable=False),
    Column("agreement_type", String(100), nullable=False),
    Column("file_checksums", JSON, nullable=False),
    Column("actor_id", Uuid(as_uuid=True), nullable=False),
    Column("deletion_id", Uuid(as_uuid=True), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class AgreementDeletion:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    agreement_id: UUID
    object_keys: tuple[str, ...]
    attempt_count: int


class AgreementDeletionRepository(Protocol):
    def claim(
        self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID
    ) -> AgreementDeletion | None: ...

    def complete(self, deletion: AgreementDeletion) -> None: ...

    def retry(
        self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime
    ) -> None: ...

    def fail(self, deletion: AgreementDeletion, *, message: str) -> None: ...


class ObjectStorage(Protocol):
    def delete(self, key: str) -> None: ...


class AgreementDeletionQueue(Protocol):
    def enqueue_deletion(
        self,
        deletion_id: UUID,
        *,
        agreement_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None: ...


@dataclass(frozen=True)
class DeletionRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 2
    max_delay_seconds: int = 60

    def may_retry(self, attempt_count: int) -> bool:
        return attempt_count < self.max_attempts

    def delay_seconds(self, attempt_count: int) -> int:
        return int(
            min(
                self.base_delay_seconds * (2 ** (attempt_count - 1)),
                self.max_delay_seconds,
            )
        )


class AgreementDeletionProcessor:
    def __init__(
        self,
        repository: AgreementDeletionRepository,
        storage: ObjectStorage,
        queue: AgreementDeletionQueue,
        *,
        retry_policy: DeletionRetryPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._queue = queue
        self._retry_policy = retry_policy or DeletionRetryPolicy()

    def handle(self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID) -> None:
        deletion = self._repository.claim(
            deletion_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if deletion is None:
            return
        try:
            for key in deletion.object_keys:
                _validate_owned_key(deletion, key)
                self._storage.delete(key)
            self._repository.complete(deletion)
        except Exception:
            message = "Agreement deletion cleanup failed"
            if not self._retry_policy.may_retry(deletion.attempt_count):
                self._repository.fail(deletion, message=message)
                return
            delay_seconds = self._retry_policy.delay_seconds(deletion.attempt_count)
            self._repository.retry(
                deletion,
                message=message,
                next_retry_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
            )
            self._queue.enqueue_deletion(
                deletion.id,
                agreement_id=deletion.agreement_id,
                organization_id=deletion.organization_id,
                workspace_id=deletion.workspace_id,
                delay_seconds=delay_seconds,
            )


class SQLAlchemyAgreementDeletionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(
        self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID
    ) -> AgreementDeletion | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id)
            record = (
                connection.execute(
                    select(deletion_requests).where(deletion_requests.c.id == deletion_id)
                )
                .mappings()
                .one_or_none()
            )
            if (
                record is None
                or record["organization_id"] != organization_id
                or record["workspace_id"] != workspace_id
            ):
                return None
            if record["state"] not in {"accepted", "retrying", "processing"}:
                return None
            attempt_count = int(record["attempt_count"])
            if record["state"] != "processing":
                attempt_count += 1
            connection.execute(
                update(deletion_requests)
                .where(deletion_requests.c.id == deletion_id)
                .values(
                    state="processing",
                    attempt_count=attempt_count,
                    processing_started_at=record["processing_started_at"] or now,
                    failure_category=None,
                    failure_message=None,
                    updated_at=now,
                )
            )
            keys = cast(list[object], record["object_keys"])
            return AgreementDeletion(
                id=deletion_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=cast(UUID, record["agreement_id"]),
                object_keys=tuple(str(key) for key in keys),
                attempt_count=attempt_count,
            )

    def complete(self, deletion: AgreementDeletion) -> None:
        self._finish(deletion, state="completed", message=None)

    def retry(self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime) -> None:
        del next_retry_at
        self._finish(deletion, state="retrying", message=message)

    def fail(self, deletion: AgreementDeletion, *, message: str) -> None:
        self._finish(deletion, state="failed", message=message)

    def _finish(self, deletion: AgreementDeletion, *, state: str, message: str | None) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            record = (
                connection.execute(
                    select(deletion_requests).where(deletion_requests.c.id == deletion.id)
                )
                .mappings()
                .one_or_none()
            )
            if (
                record is None
                or record["organization_id"] != deletion.organization_id
                or record["workspace_id"] != deletion.workspace_id
            ):
                return
            if record["state"] in {"completed", "failed"}:
                return
            values: dict[str, object] = {
                "state": state,
                "failure_category": "transient"
                if message and state == "retrying"
                else "cleanup"
                if message
                else None,
                "failure_message": message,
                "updated_at": now,
            }
            if state == "completed":
                values["completed_at"] = now
            elif state == "failed":
                values["failed_at"] = now
            connection.execute(
                update(deletion_requests)
                .where(deletion_requests.c.id == deletion.id)
                .values(**values)
            )
            if state in {"completed", "failed"}:
                connection.execute(
                    insert(deletion_audit_events).values(
                        id=uuid4(),
                        organization_id=record["organization_id"],
                        workspace_id=record["workspace_id"],
                        agreement_id=record["agreement_id"],
                        title=record["title"],
                        agreement_type=record["agreement_type"],
                        file_checksums=record["file_checksums"],
                        actor_id=record["actor_id"],
                        deletion_id=deletion.id,
                        event_type=state,
                        metadata_json={"attempt_count": deletion.attempt_count},
                        occurred_at=now,
                    )
                )


def _validate_owned_key(deletion: AgreementDeletion, key: str) -> None:
    base = f"tenants/{deletion.organization_id}/workspaces/{deletion.workspace_id}/"
    if not key.startswith((f"{base}documents/", f"{base}agreements/", f"{base}reviews/")):
        raise PermissionError("deletion object key is outside the tenant workspace")


def _set_tenant_context(connection: Any, organization_id: UUID) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
