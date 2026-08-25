from datetime import UTC, datetime
from uuid import UUID, uuid4

from _pytest.monkeypatch import MonkeyPatch
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
    RetrievalChunkEmbeddingRecord,
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)
from agreement_intelligence_api.search.repository import SQLAlchemySearchRepository
from agreement_intelligence_api.search.schemas import SearchFilters
from agreement_intelligence_api.search.service import (
    RankedChunk,
    SQLAlchemySemanticCandidateProvider,
    fuse_reciprocal_rank,
)
from agreement_intelligence_worker.ai_configuration import AIOperation, ConfigurationSnapshot
from agreement_intelligence_worker.model_gateway import (
    EmbeddingConfiguration,
    EmbeddingRequest,
    EmbeddingResponse,
    GatewayProvenance,
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


def test_semantic_candidates_keep_prior_space_available_during_a_rolling_reindex(
    monkeypatch: MonkeyPatch,
) -> None:
    active_configuration = ConfigurationSnapshot(
        operation=AIOperation.EMBEDDING,
        version="embedding-registry-v2",
        prompt_template="Embed supplied text.",
        schema={"type": "object"},
        model_route="openai:embedding-model-v2",
        parameters={},
        schema_checksum="embedding-schema-v2",
    )
    prior_configuration = ConfigurationSnapshot(
        operation=AIOperation.EMBEDDING,
        version="embedding-registry-v1",
        prompt_template="Embed supplied text.",
        schema={"type": "object"},
        model_route="openai:embedding-model-v1",
        parameters={},
        schema_checksum="embedding-schema-v1",
    )
    monkeypatch.setattr(
        "agreement_intelligence_api.search.service.resolve_configuration",
        lambda *_args, **_kwargs: active_configuration,
    )
    monkeypatch.setattr(
        "agreement_intelligence_api.search.service.resolve_configuration_by_version",
        lambda _operation, version, **_kwargs: (
            prior_configuration if version == prior_configuration.version else None
        ),
        raising=False,
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session: Session = sessionmaker(bind=engine)()
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example", subject="semantic-user", display_name="User"
    )
    organization = identity.create_organization(name="Acme", slug="acme-semantic-search")
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
    active_build = RetrievalIndexBuildRecord(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        source_checksum="sha256:source-v1",
        chunker_version="structure-aware-v1",
        state="active",
        activated_at=datetime.now(UTC),
    )
    session.add(active_build)
    session.add_all(
        [
            RetrievalChunkRecord(
                chunk_id="ready-match",
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=agreement.id,
                build_id=active_build.id,
                source_checksum=active_build.source_checksum,
                chunker_version=active_build.chunker_version,
                ordinal=1,
                heading_path=["Termination"],
                anchor_ids=["source:page:2:block:1"],
                content="Termination is permitted after a material breach.",
            ),
            RetrievalChunkRecord(
                chunk_id="unavailable-wrong-version",
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=agreement.id,
                build_id=active_build.id,
                source_checksum=active_build.source_checksum,
                chunker_version=active_build.chunker_version,
                ordinal=2,
                heading_path=["General"],
                anchor_ids=["source:page:3:block:1"],
                content="General terms.",
            ),
        ]
    )
    session.add_all(
        [
            RetrievalChunkEmbeddingRecord(
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=agreement.id,
                build_id=active_build.id,
                chunk_id="ready-match",
                index_version="embedding-v1",
                dimensions=2,
                embedding=[1.0, 0.0],
                state="ready",
                provider="hosted",
                model="embedding-model-v2",
                configuration_version="embedding-registry-v2",
                input_tokens=1,
                latency_ms=1,
                cost_usd=0.0,
                retry_outcome="not_needed",
                fallback_outcome="not_needed",
                failure_reason=None,
            ),
            RetrievalChunkEmbeddingRecord(
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=agreement.id,
                build_id=active_build.id,
                chunk_id="unavailable-wrong-version",
                index_version="embedding-v1",
                dimensions=2,
                embedding=[0.0, 1.0],
                state="ready",
                provider="hosted",
                model="embedding-model-v1",
                configuration_version="embedding-registry-v1",
                input_tokens=1,
                latency_ms=1,
                cost_usd=0.0,
                retry_outcome="not_needed",
                fallback_outcome="not_needed",
                failure_reason=None,
            ),
        ]
    )
    session.commit()
    provider = SQLAlchemySemanticCandidateProvider(
        SQLAlchemySearchRepository(session),
        gateway=_EmbeddingGateway(
            {
                "embedding-model-v2": [1.0, 0.0],
                "embedding-model-v1": [0.0, 1.0],
            }
        ),
        configuration=_embedding_configuration(),
    )

    results = provider.candidates(
        organization_id=organization.id,
        workspace_id=workspace.id,
        filters=SearchFilters(query="termination", agreement_type="client_agreement"),
        limit=50,
    )

    assert [result.chunk_id for result in results] == [
        "ready-match",
        "unavailable-wrong-version",
    ]
    assert results[0].embedding_index_version == "embedding-v1"
    session.close()
    engine.dispose()


def _embedding_configuration() -> EmbeddingConfiguration:
    return EmbeddingConfiguration(
        model="embedding-model",
        dimensions=2,
        index_version="embedding-v1",
        batch_size=32,
        max_retries=0,
        configuration_version="embedding-gateway.v1",
        input_cost_per_million_tokens=0.0,
    )


class _EmbeddingGateway:
    def __init__(self, vectors_by_model: dict[str, list[float]]) -> None:
        self._vectors_by_model = vectors_by_model

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        assert request.inputs == ("termination",)
        assert request.dimensions == 2
        assert request.model is not None
        return EmbeddingResponse(
            vectors=[self._vectors_by_model[request.model]],
            provenance=GatewayProvenance(
                provider="hosted",
                endpoint_kind="hosted",
                model=request.model,
                configuration_version="embedding-registry-v2",
                latency_ms=1,
                input_tokens=1,
                output_tokens=None,
                total_tokens=1,
                cost_usd=0.0,
                retry_outcome="not_needed",
                fallback_outcome="not_needed",
                safe_failure_reason=None,
            ),
        )
