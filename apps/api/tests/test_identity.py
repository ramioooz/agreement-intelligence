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
    assert response.json() == {"agreements_delete": True, "playbooks_manage": True}
    assert reviewer_response.status_code == 200
    assert reviewer_response.json() == {
        "agreements_delete": False,
        "playbooks_manage": False,
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
        pytest.skip(
            "Set AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL to a disposable PostgreSQL database URL "
            "to run the tenant isolation RLS integration test."
        )

    schema_name = f"tenant_isolation_{uuid4().hex}"
    base_url = make_url(postgres_url)
    scoped_url = base_url.set(query={"options": f"-csearch_path={schema_name}"}).render_as_string(
        hide_password=False
    )
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    base_engine = create_engine(postgres_url.replace("postgresql://", "postgresql+psycopg://", 1))
    scoped_engine = create_engine(scoped_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

        command.upgrade(config, "head")

        organization_a = uuid4()
        organization_b = uuid4()
        workspace_a = uuid4()
        workspace_b = uuid4()
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
            scoped_workspace_ids = set(
                connection.execute(text("SELECT id FROM workspaces")).scalars()
            )

            with pytest.raises(Exception, match="organization_id is immutable"):
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

        assert scoped_workspace_ids == {workspace_a}
    finally:
        scoped_engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
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
