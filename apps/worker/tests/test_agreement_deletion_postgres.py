import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_api.agreements.repository import (
    SQLAlchemyAgreementRepository as APIAgreementRepository,
)
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.processing.repository import (
    SQLAlchemyProcessingJobRepository as APIProcessingJobRepository,
)
from agreement_intelligence_api.processing.schemas import ProcessingJobResponse
from agreement_intelligence_api.processing.service import ProcessingJobService
from agreement_intelligence_worker.agreement_deletion import (
    AgreementDeletionProcessor,
    SQLAlchemyAgreementDeletionRepository,
)
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    JobProcessor,
    PermanentProcessingError,
    ProcessingJob,
    RetryPolicy,
    SQLAlchemyProcessingJobRepository,
    TransientProcessingError,
)
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_postgres_cleanup_is_tenant_scoped_and_purges_owned_rows(
    request: pytest.FixtureRequest,
) -> None:
    database_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL URL is required")
    schema_name = f"agreement_deletion_{uuid4().hex}"
    scoped_url = (
        make_url(database_url)
        .set(query={"options": f"-csearch_path={schema_name},public"})
        .render_as_string(hide_password=False)
    )
    base_engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    engine = create_engine(scoped_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with base_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    config = Config(str(Path(__file__).parents[2] / "api" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    command.upgrade(config, "head")

    def cleanup() -> None:
        engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        base_engine.dispose()

    request.addfinalizer(cleanup)
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    keeper_id = uuid4()
    version_one_id = uuid4()
    version_two_id = uuid4()
    keeper_version_id = uuid4()
    job_id = uuid4()
    comparison_id = uuid4()
    review_id = uuid4()
    thread_id = uuid4()
    deletion_id = uuid4()
    actor_id = uuid4()
    source_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/documents/{'a' * 64}/original.pdf"
    )
    alias_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/documents/{'c' * 64}/original.pdf"
    )
    upload_wins_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/documents/{'d' * 64}/original.pdf"
    )
    worker_wins_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/documents/{'e' * 64}/original.pdf"
    )
    analysis_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/{agreement_id}/"
        f"analysis/{'b' * 64}/document-analysis.v1.json"
    )
    comparison_key = f"comparisons/{comparison_id}/version-comparison.v1.json"
    review_key = f"reviews/{organization_id}/{workspace_id}/{review_id}/final-package/manifest.json"
    empty_json = json.dumps([])
    empty_object = json.dumps({})

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organizations (id,name,slug) VALUES (:id,'Delete test',:slug)"),
            {"id": organization_id, "slug": f"delete-{organization_id}"},
        )
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO workspaces (id,organization_id,name,slug)
                VALUES (:id,:organization_id,'Legal','legal')
                """
            ),
            {"id": workspace_id, "organization_id": organization_id},
        )
        for current_id, title in (
            (agreement_id, "Sensitive agreement"),
            (keeper_id, "Shared source keeper"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO agreements (
                        id,organization_id,workspace_id,title,agreement_type,status,
                        parties,files,processing_state,audit_metadata,audit_events,
                        deletion_requested_at
                    ) VALUES (
                        :id,:organization_id,:workspace_id,:title,'client','draft',
                        CAST(:empty_json AS json),CAST(:empty_json AS json),'completed',
                        CAST(:empty_object AS json),CAST(:empty_json AS json),
                        CASE WHEN :id=:agreement_id THEN now() ELSE NULL END
                    )
                    """
                ),
                {
                    "id": current_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "title": title,
                    "empty_json": empty_json,
                    "empty_object": empty_object,
                    "agreement_id": agreement_id,
                },
            )
        connection.execute(
            text("UPDATE agreements SET files=CAST(:files AS json) WHERE id=:id"),
            {"id": keeper_id, "files": json.dumps([{"storage_key": alias_key}])},
        )
        versions = (
            (version_one_id, agreement_id, 1, None, source_key, "a" * 64, "target-v1"),
            (version_two_id, agreement_id, 2, version_one_id, source_key, "b" * 64, "target-v2"),
            (keeper_version_id, keeper_id, 1, None, source_key, "a" * 64, "keeper-v1"),
        )
        for version_id, owner_id, number, predecessor, key, checksum, idempotency in versions:
            connection.execute(
                text(
                    """
                    INSERT INTO agreement_versions (
                        id,agreement_id,organization_id,workspace_id,version_number,
                        predecessor_version_id,file_name,content_type,storage_key,checksum,
                        byte_size,uploaded_by,processing_state,analysis_provenance,
                        idempotency_key
                    ) VALUES (
                        :id,:agreement_id,:organization_id,:workspace_id,:number,
                        :predecessor,'source.pdf','application/pdf',:key,:checksum,
                        10,:actor_id,'completed',CAST(:empty_object AS json),:idempotency
                    )
                    """
                ),
                {
                    "id": version_id,
                    "agreement_id": owner_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "number": number,
                    "predecessor": predecessor,
                    "key": key,
                    "checksum": checksum,
                    "actor_id": actor_id,
                    "empty_object": empty_object,
                    "idempotency": idempotency,
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO processing_jobs (
                    id,organization_id,workspace_id,agreement_id,version_id,
                    idempotency_key,profile,state,attempt_count,queued_at
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,:version_id,
                    'delete-job','baseline','completed',1,now()
                )
                """
            ),
            {
                "id": job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "version_id": version_two_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO processing_artifacts (
                    id,job_id,organization_id,workspace_id,agreement_id,artifact_key
                ) VALUES (
                    :id,:job_id,:organization_id,:workspace_id,:agreement_id,:artifact_key
                )
                """
            ),
            {
                "id": uuid4(),
                "job_id": job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "artifact_key": analysis_key,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO version_comparison_runs (
                    id,organization_id,workspace_id,agreement_id,baseline_version_id,
                    target_version_id,idempotency_key,analysis_version,state,
                    analysis_provenance
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,:baseline,:target,
                    'delete-comparison','v1','completed',CAST(:empty_object AS json)
                )
                """
            ),
            {
                "id": comparison_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "baseline": version_one_id,
                "target": version_two_id,
                "empty_object": empty_object,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO review_cases (
                    id,organization_id,workspace_id,agreement_id,agreement_version_id,
                    state,created_by,idempotency_key,revision
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,:version_id,
                    'open',:actor_id,'delete-review',0
                )
                """
            ),
            {
                "id": review_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "version_id": version_two_id,
                "actor_id": actor_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO question_threads (
                    id,organization_id,workspace_id,agreement_ids,created_by
                ) VALUES (
                    :id,:organization_id,:workspace_id,CAST(:agreement_ids AS json),:actor_id
                )
                """
            ),
            {
                "id": thread_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_ids": json.dumps([str(agreement_id)]),
                "actor_id": actor_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO agreement_deletion_requests (
                    id,organization_id,workspace_id,agreement_id,actor_id,title,
                    agreement_type,file_checksums,state,attempt_count,retry_cycle,
                    next_attempt_at,accepted_at,updated_at
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,:actor_id,
                    'Sensitive agreement','client',CAST(:checksums AS json),'accepted',
                    0,1,now(),now() - interval '1 minute',now()
                )
                """
            ),
            {
                "id": deletion_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "actor_id": actor_id,
                "checksums": json.dumps(["a" * 64, "b" * 64]),
            },
        )
        for category, key in (
            ("source", source_key),
            ("source", alias_key),
            ("source", upload_wins_key),
            ("source", worker_wins_key),
            ("analysis", analysis_key),
            ("comparison", comparison_key),
            ("review_manifest", review_key),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO agreement_deletion_objects (
                        id,deletion_id,organization_id,workspace_id,agreement_id,
                        category,object_key,state
                    ) VALUES (
                        :id,:deletion_id,:organization_id,:workspace_id,:agreement_id,
                        :category,:object_key,'pending'
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "deletion_id": deletion_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "agreement_id": agreement_id,
                    "category": category,
                    "object_key": key,
                },
            )
        registry_now = datetime.now(UTC)
        for key, updated_at in (
            (upload_wins_key, registry_now),
            (worker_wins_key, registry_now - timedelta(minutes=2)),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO document_object_registry (
                        id,organization_id,workspace_id,object_key,state,updated_at
                    ) VALUES (
                        :id,:organization_id,:workspace_id,:object_key,'available',:updated_at
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "object_key": key,
                    "updated_at": updated_at,
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO agreement_deletion_outbox (
                    id,deletion_id,organization_id,workspace_id,agreement_id,
                    attempt_count,next_attempt_at
                ) VALUES (
                    :id,:deletion_id,:organization_id,:workspace_id,:agreement_id,0,now()
                )
                """
            ),
            {
                "id": uuid4(),
                "deletion_id": deletion_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO agreement_deletion_audit_events (
                    id,organization_id,workspace_id,agreement_id,title,agreement_type,
                    file_checksums,actor_id,deletion_id,event_type,retry_cycle,metadata_json
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,'Sensitive agreement',
                    'client',CAST(:checksums AS json),:actor_id,:deletion_id,'requested',1,
                    CAST(:empty_object AS json)
                )
                """
            ),
            {
                "id": uuid4(),
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "checksums": json.dumps(["a" * 64, "b" * 64]),
                "actor_id": actor_id,
                "deletion_id": deletion_id,
                "empty_object": empty_object,
            },
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO agreement_deletion_objects (
                    id,deletion_id,organization_id,workspace_id,agreement_id,
                    category,object_key,state
                ) VALUES (
                    :id,:deletion_id,:organization_id,:workspace_id,:wrong_agreement_id,
                    'source',:object_key,'pending'
                )
                """
            ),
            {
                "id": uuid4(),
                "deletion_id": deletion_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "wrong_agreement_id": uuid4(),
                "object_key": source_key,
            },
        )

    class Storage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete(self, key: str) -> None:
            self.deleted.append(key)

    repository = SQLAlchemyAgreementDeletionRepository(engine)
    storage = Storage()
    assert organization_id in repository.organization_ids()
    first_outbox_claim = repository.claim_due_outbox(organization_id)
    assert first_outbox_claim is not None
    assert repository.claim_due_outbox(organization_id) is None
    repository.release_outbox(first_outbox_claim, next_attempt_at=datetime.now(UTC))
    second_outbox_claim = repository.claim_due_outbox(organization_id)
    assert second_outbox_claim is not None
    assert second_outbox_claim.lease_token != first_outbox_claim.lease_token
    repository.mark_outbox_delivered(second_outbox_claim)
    assert (
        repository.claim(
            deletion_id,
            organization_id=uuid4(),
            workspace_id=workspace_id,
        )
        is None
    )

    AgreementDeletionProcessor(repository, storage).handle(
        deletion_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    AgreementDeletionProcessor(repository, storage).handle(
        deletion_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    assert set(storage.deleted) == {worker_wins_key, analysis_key, comparison_key, review_key}
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        state = connection.execute(
            text(
                """
                SELECT state,completed_at,failure_category,failure_message
                FROM agreement_deletion_requests WHERE id=:id
                """
            ),
            {"id": deletion_id},
        ).one()
        assert state.state == "completed", state
        assert state.completed_at is not None
        tombstone = connection.execute(
            text("SELECT title,files,processing_state FROM agreements WHERE id=:id"),
            {"id": agreement_id},
        ).one()
        assert tombstone.title == "Deleted agreement"
        assert tombstone.files == []
        assert tombstone.processing_state == "deleted"
        for table_name in (
            "agreement_versions",
            "processing_jobs",
            "processing_artifacts",
            "version_comparison_runs",
            "review_cases",
            "agreement_deletion_objects",
            "agreement_deletion_outbox",
        ):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM {table_name} WHERE agreement_id=:agreement_id"),
                    {"agreement_id": agreement_id},
                )
                == 0
            )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM question_threads WHERE id=:thread_id"),
                {"thread_id": thread_id},
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    """
                SELECT count(*) FROM agreement_versions
                WHERE agreement_id=:keeper_id AND storage_key=:source_key
                """
                ),
                {"keeper_id": keeper_id, "source_key": source_key},
            )
            == 1
        )
    _assert_permanent_failure_cleanup(
        engine=engine,
        repository=repository,
        storage=storage,
        organization_id=organization_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        empty_json=empty_json,
        empty_object=empty_object,
        upload_wins_key=upload_wins_key,
        worker_wins_key=worker_wins_key,
        deletion_id=deletion_id,
    )
    _assert_exhausted_response_loss_cleanup(
        engine=engine,
        organization_id=organization_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        empty_json=empty_json,
        empty_object=empty_object,
    )


def test_artifact_intent_downgrade_refuses_live_rows_for_non_superuser_owner(
    request: pytest.FixtureRequest,
) -> None:
    database_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL URL is required")
    suffix = uuid4().hex
    role_name = f"intent_migrator_{suffix}"
    schema_name = f"intent_downgrade_{suffix}"
    role_password = f"migration-{suffix}"
    database_name = make_url(database_url).database
    assert database_name is not None
    admin_engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with admin_engine.begin() as connection:
        connection.execute(text(f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{role_password}'"))
        connection.execute(text(f'GRANT CREATE ON DATABASE "{database_name}" TO "{role_name}"'))
        connection.execute(text(f'CREATE SCHEMA "{schema_name}" AUTHORIZATION "{role_name}"'))
    role_url = (
        make_url(database_url)
        .set(
            username=role_name,
            password=role_password,
            query={"options": f"-csearch_path={schema_name},public"},
        )
        .render_as_string(hide_password=False)
    )
    role_engine = create_engine(role_url.replace("postgresql://", "postgresql+psycopg://", 1))

    def cleanup() -> None:
        role_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            connection.execute(text(f'DROP OWNED BY "{role_name}"'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
        admin_engine.dispose()

    request.addfinalizer(cleanup)
    with role_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
    config = Config(str(Path(__file__).parents[2] / "api" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", role_url.replace("%", "%%"))
    command.upgrade(config, "head")
    organization_id, workspace_id, agreement_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    with role_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organizations (id,name,slug) VALUES (:id,'Intent test',:slug)"),
            {"id": organization_id, "slug": f"intent-{organization_id}"},
        )
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO workspaces (id,organization_id,name,slug)
                VALUES (:id,:organization_id,'Legal','legal')
                """
            ),
            {"id": workspace_id, "organization_id": organization_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO agreements (
                    id,organization_id,workspace_id,title,agreement_type,status,
                    parties,files,processing_state,audit_metadata,audit_events
                ) VALUES (
                    :id,:organization_id,:workspace_id,'Intent agreement','client','draft',
                    CAST('[]' AS json),CAST('[]' AS json),'processing',
                    CAST('{}' AS json),CAST('[]' AS json)
                )
                """
            ),
            {
                "id": agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO processing_jobs (
                    id,organization_id,workspace_id,agreement_id,idempotency_key,
                    profile,state,attempt_count,claim_token,claim_lease_expires_at,queued_at
                ) VALUES (
                    :job_id,:organization_id,:workspace_id,:agreement_id,'live-claim',
                    'baseline','processing',1,:claim_token,now() + interval '5 minutes',now()
                )
                """
            ),
            {
                "job_id": job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "claim_token": uuid4(),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO processing_artifact_intents (
                    id,job_id,organization_id,workspace_id,agreement_id,
                    profile,category,artifact_key
                ) VALUES (
                    :id,:job_id,:organization_id,:workspace_id,:agreement_id,
                    'baseline','analysis',:artifact_key
                )
                """
            ),
            {
                "id": uuid4(),
                "job_id": job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "artifact_key": (
                    f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/"
                    f"{agreement_id}/analysis/{'a' * 64}/document-analysis.v1.json"
                ),
            },
        )

    with pytest.raises(RuntimeError, match="processing artifact intents are pending"):
        command.downgrade(config, "20260826_0033")

    with role_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text("DELETE FROM processing_artifact_intents WHERE job_id=:job_id"),
            {"job_id": job_id},
        )

    with pytest.raises(RuntimeError, match="processing job claims are active"):
        command.downgrade(config, "20260826_0033")

    with role_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert connection.scalar(text("SELECT count(*) FROM processing_artifact_intents")) == 0
        assert connection.scalar(
            text("SELECT claim_token IS NOT NULL FROM processing_jobs WHERE id=:job_id"),
            {"job_id": job_id},
        )
        assert connection.scalar(
            text(
                """
                SELECT relforcerowsecurity FROM pg_class
                WHERE oid='processing_artifact_intents'::regclass
                """
            )
        )


def _assert_permanent_failure_cleanup(
    *,
    engine: Engine,
    repository: SQLAlchemyAgreementDeletionRepository,
    storage: Any,
    organization_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    empty_json: str,
    empty_object: str,
    upload_wins_key: str,
    worker_wins_key: str,
    deletion_id: UUID,
) -> None:
    failed_agreement_id, failed_job_id, failed_deletion_id = uuid4(), uuid4(), uuid4()
    expected_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/{failed_agreement_id}/"
        f"analysis/{'f' * 64}/document-analysis.v1.json"
    )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO agreements (
                    id,organization_id,workspace_id,title,agreement_type,status,
                    parties,files,processing_state,audit_metadata,audit_events
                ) VALUES (
                    :id,:organization_id,:workspace_id,'Permanent failure','client','draft',
                    CAST(:empty_json AS json),CAST(:empty_json AS json),'queued',
                    CAST(:empty_object AS json),CAST(:empty_json AS json)
                )
                """
            ),
            {
                "id": failed_agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "empty_json": empty_json,
                "empty_object": empty_object,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO processing_jobs (
                    id,organization_id,workspace_id,agreement_id,idempotency_key,
                    profile,state,attempt_count,queued_at
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,
                    'permanent-failure','baseline','queued',0,now()
                )
                """
            ),
            {
                "id": failed_job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": failed_agreement_id,
            },
        )

    class PermanentFailureProcessor:
        def expected_artifact(self, job: ProcessingJob) -> CompletedArtifact:
            return CompletedArtifact(job_id=job.id, key=expected_key)

        def process(self, job: ProcessingJob) -> CompletedArtifact:
            del job
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
                connection.execute(
                    text(
                        "UPDATE agreements SET deletion_requested_at=now() WHERE id=:agreement_id"
                    ),
                    {"agreement_id": failed_agreement_id},
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO agreement_deletion_requests (
                            id,organization_id,workspace_id,agreement_id,actor_id,title,
                            agreement_type,file_checksums,state,attempt_count,retry_cycle,
                            next_attempt_at,accepted_at,completed_at,updated_at
                        ) VALUES (
                            :id,:organization_id,:workspace_id,:agreement_id,:actor_id,
                            'Permanent failure','client',CAST('[]' AS json),'completed',
                            0,1,now(),now(),now(),now()
                        )
                        """
                    ),
                    {
                        "id": failed_deletion_id,
                        "organization_id": organization_id,
                        "workspace_id": workspace_id,
                        "agreement_id": failed_agreement_id,
                        "actor_id": actor_id,
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO agreement_deletion_objects (
                            id,deletion_id,organization_id,workspace_id,agreement_id,
                            category,object_key,state
                        ) VALUES (
                            :id,:deletion_id,:organization_id,:workspace_id,:agreement_id,
                            'analysis',:object_key,'deleted'
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "deletion_id": failed_deletion_id,
                        "organization_id": organization_id,
                        "workspace_id": workspace_id,
                        "agreement_id": failed_agreement_id,
                        "object_key": expected_key,
                    },
                )
            raise PermanentProcessingError("input is invalid")

    class NoRetryQueue:
        def enqueue(self, *_: object, **__: object) -> None:
            raise AssertionError("permanent failure must not enqueue a retry")

    JobProcessor(
        SQLAlchemyProcessingJobRepository(engine), NoRetryQueue(), PermanentFailureProcessor()
    ).handle(
        failed_job_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM processing_artifact_intents WHERE job_id=:job_id"),
                {"job_id": failed_job_id},
            )
            == 0
        )
        deletion_state, object_state = connection.execute(
            text(
                """
                SELECT request.state, object.state
                FROM agreement_deletion_requests AS request
                JOIN agreement_deletion_objects AS object
                  ON object.deletion_id=request.id
                WHERE request.id=:deletion_id
                """
            ),
            {"deletion_id": failed_deletion_id},
        ).one()
        assert deletion_state == "retrying"
        assert object_state == "pending"

    AgreementDeletionProcessor(repository, storage).handle(
        failed_deletion_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert (
            connection.scalar(
                text("SELECT state FROM agreement_deletion_requests WHERE id=:id"),
                {"id": failed_deletion_id},
            )
            == "completed"
        )
        registry_states = {
            row.object_key: row.state
            for row in connection.execute(
                text(
                    """
                    SELECT object_key,state FROM document_object_registry
                    WHERE object_key IN (:upload_wins_key,:worker_wins_key)
                    """
                ),
                {
                    "upload_wins_key": upload_wins_key,
                    "worker_wins_key": worker_wins_key,
                },
            )
        }
        assert registry_states == {
            upload_wins_key: "available",
            worker_wins_key: "deleted",
        }
        assert (
            connection.scalar(
                text(
                    """
                SELECT count(*) FROM agreement_deletion_audit_events
                WHERE deletion_id=:deletion_id AND event_type='completed'
                """
                ),
                {"deletion_id": deletion_id},
            )
            == 1
        )


def _assert_exhausted_response_loss_cleanup(
    *,
    engine: Engine,
    organization_id: UUID,
    workspace_id: UUID,
    actor_id: UUID,
    empty_json: str,
    empty_object: str,
) -> None:
    agreement_id, job_id = uuid4(), uuid4()
    expected_key = (
        f"tenants/{organization_id}/workspaces/{workspace_id}/agreements/{agreement_id}/"
        f"analysis/{'9' * 64}/document-analysis.v1.json"
    )
    objects: set[str] = set()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                """
                INSERT INTO agreements (
                    id,organization_id,workspace_id,title,agreement_type,status,
                    parties,files,processing_state,audit_metadata,audit_events
                ) VALUES (
                    :id,:organization_id,:workspace_id,'Response loss','client','draft',
                    CAST(:empty_json AS json),CAST(:empty_json AS json),'queued',
                    CAST(:empty_object AS json),CAST(:empty_json AS json)
                )
                """
            ),
            {
                "id": agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "empty_json": empty_json,
                "empty_object": empty_object,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO processing_jobs (
                    id,organization_id,workspace_id,agreement_id,idempotency_key,
                    profile,state,attempt_count,queued_at
                ) VALUES (
                    :id,:organization_id,:workspace_id,:agreement_id,
                    'response-loss','baseline','queued',0,now()
                )
                """
            ),
            {
                "id": job_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
            },
        )

    class ResponseLossProcessor:
        def expected_artifact(self, job: ProcessingJob) -> CompletedArtifact:
            return CompletedArtifact(job_id=job.id, key=expected_key)

        def process(self, job: ProcessingJob) -> CompletedArtifact:
            del job
            objects.add(expected_key)
            raise TransientProcessingError("response lost after object storage accepted the put")

    class NoRetryQueue:
        def enqueue(self, *_: object, **__: object) -> None:
            raise AssertionError("exhausted processing must not enqueue a retry")

    JobProcessor(
        SQLAlchemyProcessingJobRepository(engine),
        NoRetryQueue(),
        ResponseLossProcessor(),
        retry_policy=RetryPolicy(max_attempts=1),
    ).handle(job_id, organization_id=organization_id, workspace_id=workspace_id)

    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert connection.execute(
            text(
                """
                SELECT state,artifact_key FROM processing_artifact_intents
                WHERE job_id=:job_id
                """
            ),
            {"job_id": job_id},
        ).one() == ("settled", expected_key)
    assert objects == {expected_key}

    class PermissiveIdentity:
        def __init__(self, session: Session) -> None:
            self.session = session

        def can_access_workspace(self, *_: object, **__: object) -> bool:
            return True

    class RetryPublisher:
        def __init__(self) -> None:
            self.jobs: list[UUID] = []

        def publish(
            self,
            job: ProcessingJobResponse,
            *,
            idempotency_key: str,
            profile: str,
        ) -> None:
            del idempotency_key, profile
            self.jobs.append(job.id)

    publisher = RetryPublisher()
    with Session(engine) as session:
        session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        identity = PermissiveIdentity(session)
        retried = ProcessingJobService(
            APIProcessingJobRepository(session),
            APIAgreementRepository(session),
            identity,  # type: ignore[arg-type]
            publisher,
        ).retry(
            Principal(user_id=actor_id),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            job_id=job_id,
        )
    assert retried.state == "queued"
    assert publisher.jobs == [job_id]

    processing_repository = SQLAlchemyProcessingJobRepository(engine)
    claimed = processing_repository.claim(
        job_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    assert claimed is not None
    artifact = CompletedArtifact(job_id=job_id, key=expected_key)
    assert processing_repository.expect(claimed, artifact)
    with pytest.raises(RuntimeError, match="processing job lease is held"):
        processing_repository.claim(
            job_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert (
            connection.scalar(
                text("SELECT state FROM processing_artifact_intents WHERE job_id=:job_id"),
                {"job_id": job_id},
            )
            == "expected"
        )
        connection.execute(
            text(
                """
                UPDATE processing_jobs
                SET claim_lease_expires_at=now() - interval '1 second'
                WHERE id=:job_id
                """
            ),
            {"job_id": job_id},
        )

    recovered_claim = processing_repository.claim(
        job_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    assert recovered_claim is not None
    assert recovered_claim.claim_token != claimed.claim_token
    assert recovered_claim.attempt_count == claimed.attempt_count + 1
    assert processing_repository.expect(recovered_claim, artifact)
    with pytest.raises(RuntimeError, match="processing job lease is no longer owned"):
        processing_repository.complete(
            job_id,
            artifact,
            organization_id=organization_id,
            workspace_id=workspace_id,
            claimed_job=claimed,
        )

    with Session(engine) as session, session.begin():
        session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        api_repository = APIAgreementRepository(session)
        agreement = api_repository.get(agreement_id)
        assert agreement is not None
        deletion = api_repository.accept_deletion(agreement, actor_id=actor_id)

    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert connection.execute(
            text(
                """
                SELECT object_key,state FROM agreement_deletion_objects
                WHERE deletion_id=:deletion_id
                """
            ),
            {"deletion_id": deletion.id},
        ).one() == (expected_key, "pending")

    processing_repository.fail(
        job_id,
        category="transient_exhausted",
        message="stale delivery failed",
        organization_id=organization_id,
        workspace_id=workspace_id,
        claimed_job=claimed,
    )

    class ObjectStorage:
        def delete(self, key: str) -> None:
            objects.discard(key)

    deletion_repository = SQLAlchemyAgreementDeletionRepository(engine)
    AgreementDeletionProcessor(deletion_repository, ObjectStorage()).handle(
        deletion.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    assert objects == set()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert connection.execute(
            text(
                """
                SELECT request.state,intent.state,object.state
                FROM agreement_deletion_requests AS request
                JOIN processing_artifact_intents AS intent
                  ON intent.agreement_id=request.agreement_id
                JOIN agreement_deletion_objects AS object
                  ON object.deletion_id=request.id
                 AND object.category=intent.category
                 AND object.object_key=intent.artifact_key
                WHERE request.id=:id
                """
            ),
            {"id": deletion.id},
        ).one() == ("retrying", "expected", "deleted")

    processing_repository.fail(
        job_id,
        category="transient_exhausted",
        message="retry remained ambiguous",
        organization_id=organization_id,
        workspace_id=workspace_id,
        claimed_job=recovered_claim,
    )
    AgreementDeletionProcessor(deletion_repository, ObjectStorage()).handle(
        deletion.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )

    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert (
            connection.scalar(
                text("SELECT state FROM agreement_deletion_requests WHERE id=:id"),
                {"id": deletion.id},
            )
            == "completed"
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM processing_artifact_intents WHERE job_id=:job_id"),
                {"job_id": job_id},
            )
            == 0
        )

    objects.add(expected_key)
    processing_repository.fail(
        job_id,
        category="transient_exhausted",
        message="stale worker lost the storage response after purge",
        organization_id=organization_id,
        workspace_id=workspace_id,
        claimed_job=claimed,
        expected_artifact=artifact,
    )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert connection.execute(
            text(
                """
                SELECT request.state,object.state
                FROM agreement_deletion_requests AS request
                JOIN agreement_deletion_objects AS object ON object.deletion_id=request.id
                WHERE request.id=:deletion_id AND object.object_key=:object_key
                """
            ),
            {"deletion_id": deletion.id, "object_key": expected_key},
        ).one() == ("retrying", "pending")

    AgreementDeletionProcessor(deletion_repository, ObjectStorage()).handle(
        deletion.id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    assert objects == set()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        assert (
            connection.scalar(
                text("SELECT state FROM agreement_deletion_requests WHERE id=:deletion_id"),
                {"deletion_id": deletion.id},
            )
            == "completed"
        )
