from collections.abc import Generator
from typing import Any
from uuid import uuid4

from agreement_intelligence_api.ai_config.models import AIConfigurationVersionRecord
from agreement_intelligence_api.ai_config.schemas import CreateAIConfigurationRequest
from agreement_intelligence_api.ai_config.service import AIConfigurationService
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from fastapi import HTTPException
from pytest import fixture, raises
from sqlalchemy import create_engine
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

    resolved = service.resolve(operation="document_analysis", environment="production")
    assert resolved.id == configuration.id
    assert resolved.model_route == "openai:gpt-5.4-mini"


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
