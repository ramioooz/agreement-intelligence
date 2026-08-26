import os
from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import PermissionKey, RoleKey, permissions_for
from agreement_intelligence_api.identity.routes import get_identity_service
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as inspect_database
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def test_legal_reviewer_permissions_are_explicit_and_least_privilege() -> None:
    permissions = permissions_for(RoleKey.LEGAL_REVIEWER)

    assert PermissionKey.AGREEMENTS_READ in permissions
    assert PermissionKey.REVIEWS_DECIDE in permissions
    assert PermissionKey.MEMBERS_MANAGE not in permissions


def test_role_and_permission_keys_persist_as_explicit_policy_values(session: Session) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()

    role_keys = set(session.execute(text("SELECT key FROM roles")).scalars())
    permission_keys = set(session.execute(text("SELECT key FROM permissions")).scalars())

    assert "legal_reviewer" in role_keys
    assert "reviews:decide" in permission_keys


def test_workspace_access_requires_membership_in_the_workspace(session: Session) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="reviewer-subject",
        display_name="Legal Reviewer",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    other_workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Credit",
        slug="credit",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=reviewer.id,
        role_key=RoleKey.LEGAL_REVIEWER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    principal = Principal(user_id=reviewer.id)

    assert identity.can_access_workspace(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        permission=PermissionKey.AGREEMENTS_READ,
    )
    assert not identity.can_access_workspace(
        principal,
        organization_id=organization.id,
        workspace_id=other_workspace.id,
        permission=PermissionKey.AGREEMENTS_READ,
    )


def test_workspace_membership_persists_its_organization_identifier(session: Session) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="tenant-bound-membership",
        display_name="Tenant Bound Member",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.BUSINESS_USER,
    )

    workspace_membership = identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )

    assert workspace_membership.organization_id == organization.id


def test_platform_admin_can_access_any_workspace_in_their_organization(
    session: Session,
) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    administrator = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="administrator-subject",
        display_name="Platform Administrator",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    identity.grant_membership(
        organization_id=organization.id,
        user_id=administrator.id,
        role_key=RoleKey.PLATFORM_ADMIN,
    )
    principal = Principal(user_id=administrator.id)

    assert identity.can_access_workspace(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        permission=PermissionKey.AGREEMENTS_READ,
    )


def test_business_user_lists_only_workspaces_where_they_are_a_member(
    session: Session,
) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="business-user-subject",
        display_name="Business User",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    allowed_workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    hidden_workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Credit",
        slug="credit",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.BUSINESS_USER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=allowed_workspace.id,
    )

    workspaces = identity.list_workspaces_for_organization(
        Principal(user_id=user.id), organization_id=organization.id
    )

    assert [workspace.id for workspace in workspaces or []] == [allowed_workspace.id]
    assert hidden_workspace.id not in [workspace.id for workspace in workspaces or []]


def test_workspace_listing_hides_forbidden_and_missing_organizations(session: Session) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    administrator = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="administrator-subject",
        display_name="Organization Administrator",
    )
    outsider = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="outsider-subject",
        display_name="Outside User",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    identity.grant_membership(
        organization_id=organization.id,
        user_id=administrator.id,
        role_key=RoleKey.ORGANIZATION_ADMIN,
    )

    app.dependency_overrides[get_identity_service] = lambda: identity
    try:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=administrator.id)
        authorized = TestClient(app).get(f"/identity/organizations/{organization.id}/workspaces")

        app.dependency_overrides[current_principal] = lambda: Principal(user_id=outsider.id)
        forbidden = TestClient(app).get(f"/identity/organizations/{organization.id}/workspaces")
        missing = TestClient(app).get(f"/identity/organizations/{uuid4()}/workspaces")
    finally:
        app.dependency_overrides.clear()

    assert authorized.status_code == 200
    assert authorized.json() == [
        {
            "id": str(workspace.id),
            "name": "Derivatives",
            "slug": "derivatives",
        }
    ]
    assert forbidden.status_code == 404
    assert missing.status_code == 404
    assert forbidden.json() == missing.json() == {"detail": {"code": "resource_not_found"}}


def test_principal_identity_does_not_depend_on_email() -> None:
    principal = Principal(user_id=UUID("00000000-0000-0000-0000-000000000001"))

    assert principal.user_id == UUID("00000000-0000-0000-0000-000000000001")


def test_workspace_capabilities_are_resolved_from_application_authorization(
    session: Session,
) -> None:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    administrator = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="administrator-subject",
        display_name="Platform Administrator",
    )
    organization = identity.create_organization(name="Acme Capital", slug="acme-capital")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug="derivatives",
    )
    identity.grant_membership(
        organization_id=organization.id,
        user_id=administrator.id,
        role_key=RoleKey.PLATFORM_ADMIN,
    )
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject="reviewer-subject",
        display_name="Legal Reviewer",
    )
    reviewer_membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=reviewer.id,
        role_key=RoleKey.LEGAL_REVIEWER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=reviewer_membership.id,
        workspace_id=workspace.id,
    )

    app.dependency_overrides[get_identity_service] = lambda: identity
    app.dependency_overrides[current_principal] = lambda: Principal(user_id=administrator.id)
    try:
        response = TestClient(app).get(
            f"/identity/organizations/{organization.id}/workspaces/{workspace.id}/capabilities"
        )
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=reviewer.id)
        reviewer_response = TestClient(app).get(
            f"/identity/organizations/{organization.id}/workspaces/{workspace.id}/capabilities"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "agreements_delete": True,
        "agreements_update": True,
        "playbooks_manage": True,
        "reviews_assign": True,
        "reviews_decide": True,
        "reviews_approve": True,
        "approval_policies_manage": True,
    }
    assert reviewer_response.status_code == 200
    assert reviewer_response.json() == {
        "agreements_delete": False,
        "agreements_update": False,
        "playbooks_manage": False,
        "reviews_assign": False,
        "reviews_decide": True,
        "reviews_approve": False,
        "approval_policies_manage": False,
    }


def test_initial_migration_creates_identity_tenant_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "identity.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    table_names = inspect_database(
        create_engine(f"sqlite+pysqlite:///{database_path}")
    ).get_table_names()
    assert {
        "organizations",
        "workspaces",
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "memberships",
        "workspace_memberships",
    }.issubset(table_names)


def test_initial_migration_seeds_authorization_catalog(tmp_path: Path) -> None:
    database_path = tmp_path / "identity.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            role_keys = set(connection.execute(text("SELECT key FROM roles")).scalars())
            permission_keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())
            role_permission_count = connection.execute(
                text("SELECT COUNT(*) FROM role_permissions")
            ).scalar_one()
            business_workspace_read_count = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM role_permissions
                    JOIN roles ON roles.id = role_permissions.role_id
                    JOIN permissions ON permissions.id = role_permissions.permission_id
                    WHERE roles.key = 'business_user'
                    AND permissions.key = 'workspaces:read'
                    """
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert "business_user" in role_keys
    assert "workspaces:read" in permission_keys
    assert role_permission_count > 0
    assert business_workspace_read_count == 1


def test_tenant_isolation_migration_scopes_workspace_memberships(tmp_path: Path) -> None:
    database_path = tmp_path / "tenant-isolation.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    inspector = inspect_database(create_engine(f"sqlite+pysqlite:///{database_path}"))
    columns = {column["name"] for column in inspector.get_columns("workspace_memberships")}
    foreign_keys = inspector.get_foreign_keys("workspace_memberships")
    composite_foreign_keys = {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
        for foreign_key in foreign_keys
    }

    assert "organization_id" in columns
    assert (("organization_id", "workspace_id"), "workspaces") in composite_foreign_keys
    assert (("organization_id", "membership_id"), "memberships") in composite_foreign_keys

    agreement_foreign_keys = inspector.get_foreign_keys("agreements")
    agreement_composite_foreign_keys = {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
        for foreign_key in agreement_foreign_keys
    }
    assert (("organization_id", "workspace_id"), "workspaces") in agreement_composite_foreign_keys


def test_tenant_isolation_migration_rejects_legacy_cross_tenant_workspace_memberships(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-cross-tenant.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")
    command.upgrade(config, "20260731_0002")

    organization_a = uuid4().hex
    organization_b = uuid4().hex
    workspace_id = uuid4().hex
    user_id = uuid4().hex
    membership_id = uuid4().hex
    workspace_membership_id = uuid4().hex
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO organizations (id, name, slug)
                    VALUES
                        (:organization_a, 'Tenant A', 'tenant-a'),
                        (:organization_b, 'Tenant B', 'tenant-b')
                    """
                ),
                {"organization_a": organization_a, "organization_b": organization_b},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users (id, oidc_issuer, oidc_subject, display_name)
                    VALUES (:user_id, 'issuer', 'legacy-cross-tenant-user', 'Legacy User')
                    """
                ),
                {"user_id": user_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspaces (id, organization_id, name, slug)
                    VALUES (:workspace_id, :organization_a, 'Workspace A', 'workspace-a')
                    """
                ),
                {"workspace_id": workspace_id, "organization_a": organization_a},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO memberships (id, organization_id, user_id, role_id)
                    VALUES (
                        :membership_id,
                        :organization_b,
                        :user_id,
                        '11111111111141118111111111111115'
                    )
                    """
                ),
                {
                    "membership_id": membership_id,
                    "organization_b": organization_b,
                    "user_id": user_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspace_memberships (id, workspace_id, membership_id)
                    VALUES (:workspace_membership_id, :workspace_id, :membership_id)
                    """
                ),
                {
                    "workspace_membership_id": workspace_membership_id,
                    "workspace_id": workspace_id,
                    "membership_id": membership_id,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="cross-tenant workspace memberships"):
        command.upgrade(config, "head")


def test_postgresql_tenant_isolation_enforces_rls_and_immutable_identifiers() -> None:
    postgres_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    if not postgres_url:
        raise RuntimeError(
            "AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL must reference a disposable PostgreSQL "
            "database; tenant RLS verification may not be skipped."
        )

    schema_name = f"tenant_isolation_{uuid4().hex}"
    application_role = f"tenant_rls_{uuid4().hex}"
    application_password = "tenant-rls-test-password"
    base_url = make_url(postgres_url)
    application_url = base_url.set(username=application_role, password=application_password)
    scoped_url = application_url.set(
        query={"options": f"-csearch_path={schema_name},public"}
    ).render_as_string(hide_password=False)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    base_engine = create_engine(postgres_url.replace("postgresql://", "postgresql+psycopg://", 1))
    scoped_engine = create_engine(scoped_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with base_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(
                text(
                    f'CREATE ROLE "{application_role}" LOGIN NOSUPERUSER NOBYPASSRLS '
                    f"PASSWORD '{application_password}'"
                )
            )
            connection.execute(
                text(f'CREATE SCHEMA "{schema_name}" AUTHORIZATION "{application_role}"')
            )

        command.upgrade(config, "head")

        with scoped_engine.connect() as connection:
            tables_missing_forced_rls = (
                connection.execute(
                    text(
                        """
                    SELECT relation.relname
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                    JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
                    WHERE namespace.nspname = current_schema()
                      AND relation.relkind = 'r'
                      AND attribute.attname = 'organization_id'
                      AND NOT attribute.attisdropped
                      AND NOT (relation.relrowsecurity AND relation.relforcerowsecurity)
                    ORDER BY relation.relname
                    """
                    )
                )
                .scalars()
                .all()
            )
        assert tables_missing_forced_rls == []

        organization_a = uuid4()
        organization_b = uuid4()
        workspace_a = uuid4()
        workspace_b = uuid4()
        tenant_records: dict[UUID, dict[str, UUID]] = {}
        with scoped_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO organizations (id, name, slug)
                    VALUES
                        (:organization_a, 'Tenant A', 'tenant-a'),
                        (:organization_b, 'Tenant B', 'tenant-b')
                    """
                ),
                {"organization_a": organization_a, "organization_b": organization_b},
            )
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_a)},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspaces (id, organization_id, name, slug)
                    VALUES (:workspace_id, :organization_id, 'Workspace A', 'workspace-a')
                    """
                ),
                {"workspace_id": workspace_a, "organization_id": organization_a},
            )
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_b)},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspaces (id, organization_id, name, slug)
                    VALUES (:workspace_id, :organization_id, 'Workspace B', 'workspace-b')
                    """
                ),
                {"workspace_id": workspace_b, "organization_id": organization_b},
            )

            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_a)},
            )
            for organization_id, workspace_id, suffix in (
                (organization_a, workspace_a, "a"),
                (organization_b, workspace_b, "b"),
            ):
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
                records = {
                    "agreement": uuid4(),
                    "job": uuid4(),
                    "baseline": uuid4(),
                    "target": uuid4(),
                    "comparison": uuid4(),
                    "policy": uuid4(),
                    "policy_version": uuid4(),
                    "review": uuid4(),
                    "workflow": uuid4(),
                    "outbox": uuid4(),
                    "package": uuid4(),
                }
                tenant_records[organization_id] = records
                parameters = {
                    **records,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "suffix": suffix,
                    "actor_id": uuid4(),
                }
                connection.execute(
                    text(
                        """
                        INSERT INTO agreements (
                            id, organization_id, workspace_id, title, agreement_type, status,
                            parties, files, processing_state, audit_metadata, audit_events
                        ) VALUES (
                            :agreement, :organization_id, :workspace_id, :suffix, 'nda', 'draft',
                            '[]'::jsonb, '[]'::jsonb, 'queued', '{}'::jsonb, '[]'::jsonb
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO processing_jobs (
                            id, organization_id, workspace_id, agreement_id, idempotency_key,
                            profile, state, attempt_count, queued_at
                        ) VALUES (
                            :job, :organization_id, :workspace_id, :agreement, 'job-' || :suffix,
                            'default', 'queued', 0, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    parameters,
                )
                for version_key, number in (("baseline", 1), ("target", 2)):
                    connection.execute(
                        text(
                            """
                            INSERT INTO agreement_versions (
                                id, agreement_id, organization_id, workspace_id, version_number,
                                file_name, content_type, storage_key, checksum, byte_size,
                                uploaded_by, processing_state, analysis_provenance, idempotency_key
                            ) VALUES (
                                :version_id, :agreement, :organization_id, :workspace_id, :number,
                                'agreement.pdf', 'application/pdf', :storage_key, :checksum, 1,
                                :actor_id, 'completed', '{}'::jsonb, :idempotency_key
                            )
                            """
                        ),
                        {
                            **parameters,
                            "version_id": records[version_key],
                            "number": number,
                            "storage_key": f"versions/{suffix}/{number}",
                            "checksum": f"checksum-{suffix}-{number}",
                            "idempotency_key": f"version-{suffix}-{number}",
                        },
                    )
                connection.execute(
                    text(
                        """
                        INSERT INTO version_comparison_runs (
                            id, organization_id, workspace_id, agreement_id, baseline_version_id,
                            target_version_id, processing_job_id, idempotency_key, analysis_version,
                            state, analysis_provenance
                        ) VALUES (
                            :comparison, :organization_id, :workspace_id, :agreement, :baseline,
                            :target, :job, 'comparison-' || :suffix, 'v1', 'queued', '{}'::jsonb
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO approval_policies (
                            id, organization_id, workspace_id, name, agreement_family,
                            document_direction, jurisdiction, materiality, precedence, created_by
                        ) VALUES (
                            :policy, :organization_id, :workspace_id, 'Policy ' || :suffix, 'nda',
                            'any', 'any', 'any', 1, :actor_id
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO approval_policy_versions (
                            id, organization_id, workspace_id, policy_id, version, status,
                            submitter_may_approve, allow_cross_stage_same_approver, created_by
                        ) VALUES (
                            :policy_version, :organization_id, :workspace_id, :policy, 1,
                            'published',
                            false, false, :actor_id
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO review_cases (
                            id, organization_id, workspace_id, agreement_id, state, created_by,
                            idempotency_key, revision
                        ) VALUES (
                            :review, :organization_id, :workspace_id, :agreement, 'open', :actor_id,
                            'review-' || :suffix, 0
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO review_workflows (
                            id, organization_id, workspace_id, review_id, policy_version_id,
                            checkpoint_id, state, active_stage_ordinal, revision
                        ) VALUES (
                            :workflow, :organization_id, :workspace_id, :review, :policy_version,
                            :workflow, 'waiting_for_approval', 1, 0
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO review_workflow_outbox (
                            id, workflow_id, organization_id, workspace_id, event_type,
                            correlation_id, idempotency_key
                        ) VALUES (
                            :outbox, :workflow, :organization_id, :workspace_id,
                            'review.workflow.terminal',
                            'test', 'workflow-outbox-' || :suffix
                        )
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO review_final_packages (
                            id, organization_id, workspace_id, review_id, workflow_id, state,
                            manifest_key, pdf_key, manifest_checksum, pdf_checksum
                        ) VALUES (
                            :package, :organization_id, :workspace_id, :review, :workflow,
                            'rejected', 'manifest-' || :suffix, 'pdf-' || :suffix,
                            'manifest-checksum-' || :suffix, 'pdf-checksum-' || :suffix
                        )
                        """
                    ),
                    parameters,
                )

            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(organization_a)},
            )
            scoped_workspace_ids = set(
                connection.execute(text("SELECT id FROM workspaces")).scalars()
            )
            scoped_newly_protected_ids = {
                table_name: set(connection.execute(text(f"SELECT id FROM {table_name}")).scalars())
                for table_name in (
                    "processing_jobs",
                    "version_comparison_runs",
                    "review_workflow_outbox",
                )
            }

            assert scoped_newly_protected_ids == {
                "processing_jobs": {tenant_records[organization_a]["job"]},
                "version_comparison_runs": {tenant_records[organization_a]["comparison"]},
                "review_workflow_outbox": {tenant_records[organization_a]["outbox"]},
            }

            with pytest.raises(Exception, match="row-level security"), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO workspaces (id, organization_id, name, slug)
                        VALUES (:workspace_id, :organization_b, 'Cross-tenant', 'cross-tenant')
                        """
                    ),
                    {"workspace_id": uuid4(), "organization_b": organization_b},
                )

            with (
                pytest.raises(Exception, match="organization_id is immutable"),
                connection.begin_nested(),
            ):
                connection.execute(
                    text(
                        """
                        UPDATE workspaces
                        SET organization_id = :organization_b
                        WHERE id = :workspace_id
                        """
                    ),
                    {"organization_b": organization_b, "workspace_id": workspace_a},
                )

            for mutation in (
                "UPDATE review_final_packages SET state = 'approved' WHERE id = :package_id",
                "DELETE FROM review_final_packages WHERE id = :package_id",
            ):
                with (
                    pytest.raises(Exception, match="review final packages are immutable"),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        text(mutation),
                        {"package_id": tenant_records[organization_a]["package"]},
                    )

            with (
                pytest.raises(Exception, match="terminal package snapshots are immutable"),
                connection.begin_nested(),
            ):
                connection.execute(
                    text(
                        "UPDATE review_workflow_outbox "
                        'SET package_snapshot = \'{"state":"rejected"}\'::json '
                        "WHERE id = :outbox_id"
                    ),
                    {"outbox_id": tenant_records[organization_a]["outbox"]},
                )

            for table_name, values in (
                (
                    "processing_jobs",
                    {
                        "id": uuid4(),
                        "organization_id": organization_b,
                        "workspace_id": workspace_b,
                        "agreement_id": tenant_records[organization_b]["agreement"],
                        "idempotency_key": "cross-tenant-job",
                    },
                ),
                (
                    "version_comparison_runs",
                    {
                        "id": uuid4(),
                        "organization_id": organization_b,
                        "workspace_id": workspace_b,
                        "agreement_id": tenant_records[organization_b]["agreement"],
                        "baseline_version_id": tenant_records[organization_b]["baseline"],
                        "target_version_id": tenant_records[organization_b]["target"],
                        "processing_job_id": tenant_records[organization_b]["job"],
                        "idempotency_key": "cross-tenant-comparison",
                    },
                ),
                (
                    "review_workflow_outbox",
                    {
                        "id": uuid4(),
                        "organization_id": organization_b,
                        "workspace_id": workspace_b,
                        "workflow_id": tenant_records[organization_b]["workflow"],
                        "idempotency_key": "cross-tenant-workflow-outbox",
                    },
                ),
            ):
                with (
                    pytest.raises(Exception, match="row-level security"),
                    connection.begin_nested(),
                ):
                    if table_name == "processing_jobs":
                        connection.execute(
                            text(
                                """
                                INSERT INTO processing_jobs (
                                    id, organization_id, workspace_id, agreement_id,
                                    idempotency_key,
                                    profile, state, attempt_count, queued_at
                                ) VALUES (
                                    :id, :organization_id, :workspace_id, :agreement_id,
                                    :idempotency_key, 'default', 'queued', 0, CURRENT_TIMESTAMP
                                )
                                """
                            ),
                            values,
                        )
                    elif table_name == "version_comparison_runs":
                        connection.execute(
                            text(
                                """
                                INSERT INTO version_comparison_runs (
                                    id, organization_id, workspace_id, agreement_id,
                                    baseline_version_id, target_version_id, processing_job_id,
                                    idempotency_key, analysis_version,
                                    state, analysis_provenance
                                ) VALUES (
                                    :id, :organization_id, :workspace_id, :agreement_id,
                                    :baseline_version_id, :target_version_id, :processing_job_id,
                                    :idempotency_key, 'v1', 'queued', '{}'::jsonb
                                )
                                """
                            ),
                            values,
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                INSERT INTO review_workflow_outbox (
                                    id, workflow_id, organization_id, workspace_id, event_type,
                                    correlation_id, idempotency_key
                                ) VALUES (
                                    :id, :workflow_id, :organization_id, :workspace_id, 'resume',
                                    'cross-tenant', :idempotency_key
                                )
                                """
                            ),
                            values,
                        )

        assert scoped_workspace_ids == {workspace_a}
    finally:
        scoped_engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{application_role}"'))
        base_engine.dispose()


def test_tenant_isolation_migration_enables_postgresql_row_level_security() -> None:
    migration_path = (
        Path(__file__).parents[1] / "migrations" / "versions" / "20260731_0003_tenant_isolation.py"
    )

    migration_sql = migration_path.read_text()

    for table_name in ("workspaces", "memberships", "workspace_memberships", "agreements"):
        assert f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY" in migration_sql
        assert f"CREATE POLICY tenant_isolation_{table_name}" in migration_sql
    assert "current_setting('app.organization_id', true)::uuid" in migration_sql
    assert "CREATE TRIGGER prevent_{table_name}_organization_change" in migration_sql
    assert "prevent_organization_id_change" in migration_sql


def test_tenant_rls_hardening_migration_covers_scoped_and_child_tables() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260824_0030_tenant_rls_hardening.py"
    )
    migration_sql = migration_path.read_text()

    expected_tenant_tables = {
        "workspaces",
        "memberships",
        "workspace_memberships",
        "agreements",
        "processing_jobs",
        "agreement_deletion_audit_events",
        "legal_playbooks",
        "playbook_versions",
        "playbook_rules",
        "playbook_audit_events",
        "playbook_evaluations",
        "playbook_findings",
        "review_decisions",
        "review_audit_events",
        "mcp_audit_events",
        "retrieval_index_builds",
        "retrieval_chunks",
        "retrieval_chunk_embeddings",
        "question_threads",
        "question_turns",
        "question_audit_events",
        "agreement_versions",
        "agreement_version_audit_events",
        "version_comparison_runs",
        "version_comparison_changes",
        "audit_events",
        "approval_policies",
        "approval_policy_versions",
        "approval_policy_stages",
        "approval_policy_audit_events",
        "review_cases",
        "review_assignments",
        "review_comments",
        "review_notification_events",
        "review_workflows",
        "review_workflow_stages",
        "review_workflow_decisions",
        "review_workflow_outbox",
        "review_final_packages",
        "processing_artifacts",
        "processing_outbox",
    }

    for table_name in expected_tenant_tables:
        assert table_name in migration_sql
    assert "ENABLE ROW LEVEL SECURITY" in migration_sql
    assert "FORCE ROW LEVEL SECURITY" in migration_sql
    assert "current_setting('app.organization_id', true)::uuid" in migration_sql
