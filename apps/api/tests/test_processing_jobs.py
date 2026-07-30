import json
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.processing.queue import (
    ProcessingOutboxDispatcher,
    SQSProcessingQueuePublisher,
)
from agreement_intelligence_api.processing.routes import get_queue_publisher
from agreement_intelligence_api.processing.schemas import (
    ProcessingJobResponse,
    SubmitProcessingJobRequest,
)
from agreement_intelligence_api.processing.service import (
    IdempotencyKeyConflictError,
    ProcessingJobService,
)
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy import inspect as inspect_database
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@dataclass
class PublishedJobs:
    jobs: list[ProcessingJobResponse]
    fail_publish: bool = False

    def publish(self, job: ProcessingJobResponse, *, idempotency_key: str, profile: str) -> None:
        if self.fail_publish:
            raise RuntimeError("sqs unavailable")
        self.jobs.append(job)


@dataclass
class ClientFactory:
    published_jobs: PublishedJobs

    def __call__(self, user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)


@fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@fixture
def client_for_session(session: Session) -> Generator[ClientFactory]:
    app.dependency_overrides[get_session] = lambda: session
    published_jobs = PublishedJobs(jobs=[])
    app.dependency_overrides[get_queue_publisher] = lambda: published_jobs

    try:
        yield ClientFactory(published_jobs=published_jobs)
    finally:
        app.dependency_overrides.clear()


def _scope_query(organization: Organization, workspace: Workspace) -> dict[str, str]:
    return {"organization_id": str(organization.id), "workspace_id": str(workspace.id)}


def _create_business_user_scope(session: Session) -> tuple[UUID, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"user-{uuid4()}",
        display_name="Business User",
    )
    organization = identity.create_organization(name=f"Acme {uuid4()}", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug=f"derivatives-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.BUSINESS_USER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return user.id, organization, workspace


def _agreement_payload() -> dict[str, object]:
    return {"title": "Processing agreement", "agreement_type": "client", "files": []}


def test_submission_is_idempotent_and_conflicting_payload_is_rejected(
    session: Session,
    client_for_session: ClientFactory,
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    agreement = client.post(
        "/agreements", params=_scope_query(organization, workspace), json=_agreement_payload()
    )
    assert agreement.status_code == 201

    url = f"/agreements/{agreement.json()['id']}/processing-jobs"
    headers = {"Idempotency-Key": "agreement-processing-v1"}
    first = client.post(
        url,
        params=_scope_query(organization, workspace),
        headers=headers,
        json={"profile": "baseline"},
    )
    repeated = client.post(
        url,
        params=_scope_query(organization, workspace),
        headers=headers,
        json={"profile": "baseline"},
    )
    conflict = client.post(
        url,
        params=_scope_query(organization, workspace),
        headers={**headers, "X-Correlation-ID": "11111111-1111-4111-8111-111111111111"},
        json={"profile": "priority"},
    )

    assert first.status_code == 202
    assert first.json()["agreement_id"] == agreement.json()["id"]
    assert first.json()["state"] == "queued"
    assert first.json()["attempt_count"] == 0
    assert first.json()["failure_category"] is None
    assert first.json()["failure_message"] is None
    assert first.json()["next_retry_at"] is None
    assert first.json()["queued_at"]
    assert first.json()["retry_permitted"] is False
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "idempotency_key_conflict",
        "message": "Idempotency key was already used with a different processing request",
        "correlation_id": "11111111-1111-4111-8111-111111111111",
    }
    assert [job.id for job in client_for_session.published_jobs.jobs] == [UUID(first.json()["id"])]


def test_failed_job_status_exposes_permitted_retry_and_retry_requeues_it(
    session: Session,
    client_for_session: ClientFactory,
) -> None:
    from agreement_intelligence_api.processing.models import ProcessingJobRecord

    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    agreement = client.post(
        "/agreements", params=_scope_query(organization, workspace), json=_agreement_payload()
    )
    assert agreement.status_code == 201
    scope = _scope_query(organization, workspace)
    submitted = client.post(
        f"/agreements/{agreement.json()['id']}/processing-jobs",
        params=scope,
        headers={"Idempotency-Key": "retryable-job"},
        json={"profile": "baseline"},
    )
    assert submitted.status_code == 202
    job = session.get(ProcessingJobRecord, UUID(submitted.json()["id"]))
    assert job is not None
    job.state = "failed"
    job.attempt_count = 3
    job.failure_category = "transient_exhausted"
    job.failure_message = "Temporary provider failure"
    session.flush()

    status = client.get(
        f"/agreements/{agreement.json()['id']}/processing-jobs/{submitted.json()['id']}",
        params=scope,
    )
    retried = client.post(
        f"/agreements/{agreement.json()['id']}/processing-jobs/{submitted.json()['id']}/retry",
        params=scope,
    )

    assert status.status_code == 200
    assert status.json()["state"] == "failed"
    assert status.json()["attempt_count"] == 3
    assert status.json()["failure_category"] == "transient_exhausted"
    assert status.json()["retry_permitted"] is True
    assert retried.status_code == 202
    assert retried.json()["state"] == "queued"
    assert retried.json()["attempt_count"] == 3
    assert retried.json()["failure_category"] is None
    assert retried.json()["next_retry_at"] is None
    assert retried.json()["retry_permitted"] is False
    assert [job.id for job in client_for_session.published_jobs.jobs] == [
        UUID(submitted.json()["id"]),
        UUID(submitted.json()["id"]),
    ]


def test_permanent_failure_is_not_retryable(
    session: Session,
    client_for_session: ClientFactory,
) -> None:
    from agreement_intelligence_api.processing.models import ProcessingJobRecord

    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    agreement = client.post(
        "/agreements", params=_scope_query(organization, workspace), json=_agreement_payload()
    )
    assert agreement.status_code == 201
    scope = _scope_query(organization, workspace)
    submitted = client.post(
        f"/agreements/{agreement.json()['id']}/processing-jobs",
        params=scope,
        headers={"Idempotency-Key": "permanent-job"},
        json={"profile": "baseline"},
    )
    job = session.get(ProcessingJobRecord, UUID(submitted.json()["id"]))
    assert job is not None
    job.state = "failed"
    job.failure_category = "permanent"
    job.failure_message = "Unsupported agreement type"
    session.flush()

    status = client.get(
        f"/agreements/{agreement.json()['id']}/processing-jobs/{submitted.json()['id']}",
        params=scope,
    )
    retried = client.post(
        f"/agreements/{agreement.json()['id']}/processing-jobs/{submitted.json()['id']}/retry",
        params=scope,
    )

    assert status.status_code == 200
    assert status.json()["retry_permitted"] is False
    assert retried.status_code == 409
    assert retried.json()["code"] == "retry_not_permitted"


def test_idempotency_insert_race_returns_existing_job_or_stable_conflict(
    session: Session,
    client_for_session: ClientFactory,
) -> None:
    from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
    from agreement_intelligence_api.processing.models import ProcessingJobRecord
    from agreement_intelligence_api.processing.repository import SQLAlchemyProcessingJobRepository
    from agreement_intelligence_api.processing.schemas import ProcessingJobResponse
    from sqlalchemy.exc import IntegrityError

    class RaceRepository(SQLAlchemyProcessingJobRepository):
        simulate_next_create_race = False

        def by_idempotency_key(
            self, agreement_id: UUID, idempotency_key: str
        ) -> ProcessingJobRecord | None:
            if self.simulate_next_create_race:
                return None
            return super().by_idempotency_key(agreement_id, idempotency_key)

        def create(self, record: ProcessingJobRecord) -> ProcessingJobResponse:
            if self.simulate_next_create_race:
                self.simulate_next_create_race = False
                raise IntegrityError("insert into processing_jobs", {}, Exception("unique"))
            return super().create(record)

    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    agreement = client.post(
        "/agreements", params=_scope_query(organization, workspace), json=_agreement_payload()
    )
    assert agreement.status_code == 201
    agreement_id = UUID(agreement.json()["id"])
    repository = RaceRepository(session)
    service = ProcessingJobService(
        repository,
        SQLAlchemyAgreementRepository(session),
        IdentityService(session),
        client_for_session.published_jobs,
    )
    principal = Principal(user_id=user_id)
    request = SubmitProcessingJobRequest(profile="baseline")

    first, _ = service.submit(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement_id,
        idempotency_key="race-key",
        request=request,
    )

    repository.simulate_next_create_race = True

    repeated, created = service.submit(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement_id,
        idempotency_key="race-key",
        request=request,
    )

    assert created is False
    assert repeated.id == first.id
    assert [job.id for job in client_for_session.published_jobs.jobs] == [first.id]

    repository.simulate_next_create_race = True

    try:
        service.submit(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            idempotency_key="race-key",
            request=SubmitProcessingJobRequest(profile="priority"),
        )
    except IdempotencyKeyConflictError:
        pass
    else:
        raise AssertionError("conflicting idempotent race did not raise")


def test_processing_migration_creates_jobs_table(tmp_path: Path) -> None:
    database_path = tmp_path / "processing.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    table_names = inspect_database(
        create_engine(f"sqlite+pysqlite:///{database_path}")
    ).get_table_names()
    assert "processing_jobs" in table_names
    assert "processing_artifacts" in table_names
    assert "processing_outbox" in table_names


def test_sqs_processing_publisher_sends_standard_queue_message_without_fifo_metadata() -> None:
    class RecordingSQSClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def send_message(self, **request: object) -> None:
            self.messages.append(request)

    client = RecordingSQSClient()
    job = ProcessingJobResponse(
        id=uuid4(),
        agreement_id=uuid4(),
        state="queued",
        attempt_count=0,
        failure_category=None,
        failure_message=None,
        next_retry_at=None,
        queued_at=datetime.now(UTC),
        processing_started_at=None,
        completed_at=None,
        failed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        retry_permitted=False,
    )
    publisher = SQSProcessingQueuePublisher(
        client=client,
        queue_url="https://sqs.example/processing",
    )

    publisher.publish(job, idempotency_key="agreement-processing-v1", profile="baseline")

    assert len(client.messages) == 1
    message = client.messages[0]
    assert message["QueueUrl"] == "https://sqs.example/processing"
    assert "MessageGroupId" not in message
    assert "MessageDeduplicationId" not in message
    assert json.loads(str(message["MessageBody"])) == {
        "job_id": str(job.id),
        "agreement_id": str(job.agreement_id),
        "idempotency_key": "agreement-processing-v1",
        "profile": "baseline",
        "attempt_count": 0,
        "queued_at": job.queued_at.isoformat(),
    }


def test_sqs_processing_publisher_sends_fifo_metadata_for_fifo_queue() -> None:
    class RecordingSQSClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def send_message(self, **request: object) -> None:
            self.messages.append(request)

    client = RecordingSQSClient()
    job = ProcessingJobResponse(
        id=uuid4(),
        agreement_id=uuid4(),
        state="queued",
        attempt_count=0,
        failure_category=None,
        failure_message=None,
        next_retry_at=None,
        queued_at=datetime.now(UTC),
        processing_started_at=None,
        completed_at=None,
        failed_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        retry_permitted=False,
    )
    publisher = SQSProcessingQueuePublisher(
        client=client,
        queue_url="https://sqs.example/processing.fifo",
    )

    publisher.publish(job, idempotency_key="agreement-processing-v1", profile="baseline")

    assert len(client.messages) == 1
    message = client.messages[0]
    assert message["MessageGroupId"] == str(job.agreement_id)
    assert message["MessageDeduplicationId"] == (
        f"{job.id}:agreement-processing-v1:{job.attempt_count}:{job.queued_at.isoformat()}"
    )
    assert json.loads(str(message["MessageBody"])) == {
        "job_id": str(job.id),
        "agreement_id": str(job.agreement_id),
        "idempotency_key": "agreement-processing-v1",
        "profile": "baseline",
        "attempt_count": 0,
        "queued_at": job.queued_at.isoformat(),
    }


def test_submit_persists_pending_outbox_when_publish_fails_then_replay_sends_it(
    session: Session,
    client_for_session: ClientFactory,
) -> None:
    from agreement_intelligence_api.processing.models import ProcessingOutboxRecord

    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    client_for_session.published_jobs.fail_publish = True
    agreement = client.post(
        "/agreements", params=_scope_query(organization, workspace), json=_agreement_payload()
    )
    assert agreement.status_code == 201

    submitted = client.post(
        f"/agreements/{agreement.json()['id']}/processing-jobs",
        params=_scope_query(organization, workspace),
        headers={"Idempotency-Key": "publish-failure"},
        json={"profile": "baseline"},
    )

    assert submitted.status_code == 202
    pending = session.query(ProcessingOutboxRecord).one()
    assert pending.job_id == UUID(submitted.json()["id"])
    assert pending.delivered_at is None
    assert client_for_session.published_jobs.jobs == []

    client_for_session.published_jobs.fail_publish = False
    dispatched = ProcessingOutboxDispatcher(
        session=session,
        publisher=client_for_session.published_jobs,
    ).dispatch_pending()

    assert dispatched == 1
    assert [job.id for job in client_for_session.published_jobs.jobs] == [
        UUID(submitted.json()["id"])
    ]
    assert pending.delivered_at is not None
