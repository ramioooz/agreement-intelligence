from datetime import UTC, datetime
from uuid import UUID, uuid4

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import CreateAgreementRequest, Party
from agreement_intelligence_api.agreements.service import AgreementService
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.retrieval.models import (
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)
from agreement_intelligence_api.search.service import (
    RankedChunk,
    fuse_reciprocal_rank,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _chunk(*, chunk_id: str, agreement_id: UUID | None = None) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        agreement_id=agreement_id or uuid4(),
        agreement_title="Master agreement",
        agreement_type="client_agreement",
        agreement_status="active",
        source_checksum="sha256:source",
        chunker_version="structure-aware-v1",
        build_id=uuid4(),
        anchor_ids=("source:page:1:block:1",),
        content="Termination rights apply on material breach.",
    )


def test_rrf_fuses_lexical_and_semantic_ranks_deterministically() -> None:
    shared = _chunk(chunk_id="shared")
    lexical_only = _chunk(chunk_id="lexical")
    semantic_only = _chunk(chunk_id="semantic")

    results = fuse_reciprocal_rank(
        lexical=[shared, lexical_only],
        semantic=[semantic_only, shared],
        limit=20,
    )

    assert [result.chunk_id for result in results] == ["shared", "semantic", "lexical"]
    assert results[0].lexical_rank == 1
    assert results[0].semantic_rank == 2
    assert results[0].fused_score == (1 / 61) + (1 / 62)


def test_rrf_is_lexical_only_when_semantic_provider_is_unavailable() -> None:
    first = _chunk(chunk_id="first")
    second = _chunk(chunk_id="second")

    results = fuse_reciprocal_rank(lexical=[first, second], semantic=[], limit=20)

    assert [result.chunk_id for result in results] == ["first", "second"]
    assert results[0].semantic_rank is None


def test_search_filters_results_and_never_returns_cross_tenant_evidence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session: Session = sessionmaker(bind=engine)()
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example", subject="search-user", display_name="User"
    )
    outsider = identity.provision_user(
        issuer="https://identity.example", subject="search-outsider", display_name="Outsider"
    )
    organization = identity.create_organization(name="Acme", slug="acme-search")
    workspace = identity.create_workspace(
        organization_id=organization.id, name="Legal", slug="legal"
    )
    membership = identity.grant_membership(
        organization_id=organization.id, user_id=user.id, role_key=RoleKey.BUSINESS_USER
    )
    identity.grant_workspace_membership(
        organization_id=organization.id, membership_id=membership.id, workspace_id=workspace.id
    )
    session.commit()
    agreement = AgreementService(SQLAlchemyAgreementRepository(session), identity).create(
        Principal(user_id=user.id),
        organization_id=organization.id,
        workspace_id=workspace.id,
        request=CreateAgreementRequest(
            title="Acme master agreement",
            agreement_type="client_agreement",
            status="active",
            parties=[Party(name="Acme", role="client")],
        ),
    )
    build = RetrievalIndexBuildRecord(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        source_checksum="sha256:source-v1",
        chunker_version="structure-aware-v1",
        state="active",
        activated_at=datetime.now(UTC),
    )
    session.add(build)
    session.add(
        RetrievalChunkRecord(
            chunk_id="term-1",
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement.id,
            build_id=build.id,
            source_checksum=build.source_checksum,
            chunker_version=build.chunker_version,
            ordinal=1,
            heading_path=["Termination"],
            anchor_ids=["source:page:2:block:1"],
            content="Termination is permitted after a material breach.",
        )
    )
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    try:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user.id)
        client = TestClient(app)
        response = client.get(
            "/search",
            params={
                "organization_id": str(organization.id),
                "workspace_id": str(workspace.id),
                "query": "termination",
                "agreement_type": "client_agreement",
                "party": "acme",
                "source_version": "sha256:source-v1",
            },
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["citation"]["anchor_ids"] == ["source:page:2:block:1"]
        assert response.json()["items"][0]["semantic_rank"] is None

        app.dependency_overrides[current_principal] = lambda: Principal(user_id=outsider.id)
        denied = client.get(
            "/search",
            params={
                "organization_id": str(organization.id),
                "workspace_id": str(workspace.id),
                "query": "termination",
            },
        )
        assert denied.status_code == 404
        assert "items" not in denied.json()
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
