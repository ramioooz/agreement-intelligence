import json
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.ai_config.models import AIConfigurationVersionRecord
from agreement_intelligence_api.ai_config.schemas import CreateAIConfigurationRequest
from agreement_intelligence_api.ai_config.service import AIConfigurationService
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.models import (
    ProcessingJobRecord,
    ProcessingOutboxRecord,
)
from agreement_intelligence_api.processing.schemas import ProcessingJobResponse
from agreement_intelligence_api.retrieval.models import RetrievalIndexBuildRecord
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from pytest import fixture, raises
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def _scope(session: Session, role: RoleKey) -> tuple[Principal, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"{role.value}-{uuid4()}",
        display_name="Registry test user",
    )
    organization = identity.create_organization(name="Acme", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Commercial",
        slug=f"commercial-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id, user_id=user.id, role_key=role
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return Principal(user_id=user.id), organization, workspace


def _request(**overrides: Any) -> CreateAIConfigurationRequest:
    payload = {
        "operation": "document_analysis",
        "version": "1.0.0",
        "prompt_template": "Classify only the supplied agreement evidence.",
        "schema": {"type": "object", "required": ["classification"]},
        "model_route": "openai:gpt-5.4-mini",
        "parameters": {"temperature": 0},
    }
    payload.update(overrides)
    return CreateAIConfigurationRequest.model_validate(payload)


def _service(session: Session) -> AIConfigurationService:
    return AIConfigurationService(session, IdentityService(session))


def test_platform_admin_creates_a_draft_configuration_with_server_checksums(
    session: Session,
) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)

    configuration = _service(session).create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )

    assert configuration.status == "draft"
    assert configuration.version == "1.0.0"
    assert configuration.prompt_checksum != ""
    assert configuration.schema_checksum != ""


def test_published_configuration_rejects_service_mutation_and_database_update(
    session: Session,
) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    service = _service(session)
    configuration = service.create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )
    service.publish(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        configuration_id=configuration.id,
    )

    with raises(HTTPException, match="published_ai_configuration_immutable"):
        service.update_prompt(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            configuration_id=configuration.id,
            prompt_template="A mutated prompt.",
        )
    record = session.get(AIConfigurationVersionRecord, configuration.id)
    assert record is not None
    assert record.prompt_template == "Classify only the supplied agreement evidence."


def test_duplicate_operation_version_is_rejected(session: Session) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    service = _service(session)
    service.create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )

    with raises(HTTPException, match="ai_configuration_version_conflict"):
        service.create(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            request=_request(),
        )


def test_environment_promotion_resolves_the_selected_published_version(session: Session) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    service = _service(session)
    configuration = service.create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )
    service.publish(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        configuration_id=configuration.id,
    )

    service.promote(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        configuration_id=configuration.id,
        environment="production",
    )

    resolved = service.resolve(
        organization_id=organization.id,
        workspace_id=workspace.id,
        operation="document_analysis",
        environment="production",
    )
    assert resolved.id == configuration.id
    assert resolved.model_route == "openai:gpt-5.4-mini"


def test_publish_rejects_unsupported_routes_and_provider_parameters(session: Session) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    service = _service(session)
    invalid_requests = (
        _request(version="2.0.0", model_route="unsupported:model"),
        _request(
            operation="embedding",
            version="3.0.0",
            model_route="openai:text-embedding-3-small",
            parameters={"temperature": 0},
        ),
    )

    for request in invalid_requests:
        configuration = service.create(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            request=request,
        )
        with raises(HTTPException) as error:
            service.publish(
                principal,
                organization_id=organization.id,
                workspace_id=workspace.id,
                configuration_id=configuration.id,
            )
        assert error.value.status_code == 422
        assert error.value.detail == {"code": "unsupported_ai_configuration"}


def test_publish_rejects_a_malformed_json_schema(session: Session) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    service = _service(session)
    configuration = service.create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(schema={"type": "not-a-json-schema-type"}),
    )

    with raises(HTTPException) as error:
        service.publish(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            configuration_id=configuration.id,
        )

    assert error.value.status_code == 422
    assert error.value.detail == {"code": "invalid_ai_configuration_schema"}


def test_embedding_promotion_durably_enqueues_each_active_agreement_once(
    session: Session,
) -> None:
    principal, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    in_scope = [
        _active_indexed_agreement(
            session,
            organization_id=organization.id,
            workspace_id=workspace.id,
            suffix=suffix,
        )
        for suffix in ("one", "two")
    ]
    archived = _active_indexed_agreement(
        session,
        organization_id=organization.id,
        workspace_id=workspace.id,
        suffix="archived",
        archived=True,
    )
    _, other_organization, other_workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    other_scope = _active_indexed_agreement(
        session,
        organization_id=other_organization.id,
        workspace_id=other_workspace.id,
        suffix="other-scope",
    )
    session.commit()
    publisher = _QueuePublisher()
    service = AIConfigurationService(session, IdentityService(session), queue=publisher)
    configuration = service.create(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(
            operation="embedding",
            version="2.0.0",
            prompt_template="Embed only the supplied canonical chunk.",
            schema={"type": "object"},
            model_route="openai:text-embedding-3-small",
            parameters={"encoding_format": "float"},
        ),
    )
    service.publish(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        configuration_id=configuration.id,
    )

    for _ in range(2):
        service.promote(
            principal,
            organization_id=organization.id,
            workspace_id=workspace.id,
            configuration_id=configuration.id,
            environment="local",
        )

    jobs = session.scalars(
        select(ProcessingJobRecord).where(
            ProcessingJobRecord.profile == f"embedding-reindex:{configuration.id}"
        )
    ).all()
    outbox = session.scalars(
        select(ProcessingOutboxRecord).where(
            ProcessingOutboxRecord.profile == f"embedding-reindex:{configuration.id}"
        )
    ).all()
    assert {job.agreement_id for job in jobs} == {agreement.id for agreement in in_scope}
    assert archived.id not in {job.agreement_id for job in jobs}
    assert other_scope.id not in {job.agreement_id for job in jobs}
    assert len(outbox) == 2
    assert len(publisher.jobs) == 2
    assert all(message.profile == f"embedding-reindex:{configuration.id}" for message in outbox)


def test_non_administrator_cannot_publish_configuration(session: Session) -> None:
    administrator, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    configuration = _service(session).create(
        administrator,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )
    non_administrator, _, _ = _scope(session, RoleKey.LEGAL_REVIEWER)

    with raises(HTTPException) as error:
        _service(session).publish(
            non_administrator,
            organization_id=organization.id,
            workspace_id=workspace.id,
            configuration_id=configuration.id,
        )

    assert error.value.status_code == 404


def test_configuration_identifier_cannot_be_read_published_or_promoted_across_scopes(
    session: Session,
) -> None:
    administrator, organization, workspace = _scope(session, RoleKey.PLATFORM_ADMIN)
    configuration = _service(session).create(
        administrator,
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=_request(),
    )
    other_administrator, other_organization, other_workspace = _scope(
        session, RoleKey.PLATFORM_ADMIN
    )
    service = _service(session)

    for action in (
        lambda: service.get(
            other_administrator,
            organization_id=other_organization.id,
            workspace_id=other_workspace.id,
            configuration_id=configuration.id,
        ),
        lambda: service.publish(
            other_administrator,
            organization_id=other_organization.id,
            workspace_id=other_workspace.id,
            configuration_id=configuration.id,
        ),
        lambda: service.promote(
            other_administrator,
            organization_id=other_organization.id,
            workspace_id=other_workspace.id,
            configuration_id=configuration.id,
            environment="production",
        ),
    ):
        with raises(HTTPException) as error:
            action()
        assert error.value.status_code == 404
    assert (
        service.resolve(
            organization_id=other_organization.id,
            workspace_id=other_workspace.id,
            operation="document_analysis",
            environment="production",
            configuration_id=configuration.id,
        )
        is None
    )


class _QueuePublisher:
    def __init__(self) -> None:
        self.jobs: list[ProcessingJobResponse] = []

    def publish(self, job: ProcessingJobResponse, *, idempotency_key: str, profile: str) -> None:
        del idempotency_key, profile
        self.jobs.append(job)


def _active_indexed_agreement(
    session: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    suffix: str,
    archived: bool = False,
) -> AgreementRecord:
    agreement = AgreementRecord(
        organization_id=organization_id,
        workspace_id=workspace_id,
        title=f"Agreement {suffix}",
        agreement_type="client_agreement",
        status="active",
        parties=[],
        files=[],
        processing_state="completed",
        audit_metadata={},
        audit_events=[],
        archived_at=datetime.now(UTC) if archived else None,
    )
    session.add(agreement)
    session.flush()
    session.add(
        RetrievalIndexBuildRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement.id,
            source_checksum=f"sha256:{suffix}",
            chunker_version="structure-aware.v1",
            state="active",
            activated_at=datetime.now(UTC),
        )
    )
    return agreement


def test_postgresql_migration_rejects_published_configuration_mutation() -> None:
    postgres_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    if not postgres_url:
        return

    schema_name = f"ai_configuration_{uuid4().hex}"
    scoped_url = (
        make_url(postgres_url)
        .set(query={"options": f"-csearch_path={schema_name},public"})
        .render_as_string(hide_password=False)
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    base_engine = create_engine(postgres_url.replace("postgresql://", "postgresql+psycopg://", 1))
    scoped_engine = create_engine(scoped_url.replace("postgresql://", "postgresql+psycopg://", 1))
    organization_id = uuid4()
    workspace_id = uuid4()
    user_id = uuid4()
    configuration_id = uuid4()
    try:
        with base_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        command.upgrade(config, "head")
        with scoped_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) "
                    "VALUES (:id, 'AI Configuration', 'ai-configuration')"
                ),
                {"id": organization_id},
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                    "VALUES (:id, 'https://issuer.example', 'ai-configuration', 'AI Configuration')"
                ),
                {"id": user_id},
            )
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_id)},
            )
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, organization_id, name, slug) "
                    "VALUES (:id, :organization_id, 'AI Configuration', 'ai-configuration')"
                ),
                {"id": workspace_id, "organization_id": organization_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ai_configuration_versions (
                        id, organization_id, workspace_id, operation, version,
                        prompt_template, prompt_checksum, schema_json, schema_checksum,
                        model_route, parameters_json, status, created_by
                    ) VALUES (
                        :id, :organization_id, :workspace_id, 'embedding', '1.0.0',
                        'Embed supplied text.', 'prompt', CAST(:schema AS json), 'schema',
                        'openai:text-embedding-3-small', CAST(:parameters AS json),
                        'published', :user_id
                    )
                    """
                ),
                {
                    "id": configuration_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "schema": json.dumps({"type": "object"}),
                    "parameters": json.dumps({}),
                    "user_id": user_id,
                },
            )
        for statement in (
            "UPDATE ai_configuration_versions SET prompt_template = 'mutated' WHERE id = :id",
            "DELETE FROM ai_configuration_versions WHERE id = :id",
        ):
            with (
                raises(DatabaseError, match="published AI configurations are immutable"),
                scoped_engine.begin() as connection,
            ):
                connection.execute(text(statement), {"id": configuration_id})
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        scoped_engine.dispose()
        base_engine.dispose()
