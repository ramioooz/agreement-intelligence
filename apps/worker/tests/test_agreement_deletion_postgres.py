import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agreement_intelligence_worker.agreement_deletion import (
    AgreementDeletionProcessor,
    SQLAlchemyAgreementDeletionRepository,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_postgres_cleanup_is_tenant_scoped_and_purges_owned_rows() -> None:
    database_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL URL is required")
    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
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
                    0,1,now(),now(),now()
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

    assert set(storage.deleted) == {analysis_key, comparison_key, review_key}
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        state = connection.execute(
            text(
                """
                SELECT state,completed_at FROM agreement_deletion_requests WHERE id=:id
                """
            ),
            {"id": deletion_id},
        ).one()
        assert state.state == "completed"
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
