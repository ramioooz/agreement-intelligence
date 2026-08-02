from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.playbooks.models import (
    LegalPlaybookRecord,
    PlaybookRuleRecord,
    PlaybookVersionRecord,
)
from agreement_intelligence_api.reviews.export import _render_pdf
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
    ReviewDecisionRecord,
)
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@pytest.fixture
def client_for_session(session: Session) -> Generator[Callable[[UUID], TestClient]]:
    app.dependency_overrides[get_session] = lambda: session
    app.state.document_storage = _Storage()

    def build_client(user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()
        del app.state.document_storage


def test_reviewer_decisions_are_append_only_and_exported_with_citations(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_review(session)
    client = client_for_session(seeded.reviewer_id)

    accepted = client.post(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=seeded.scope,
        json={
            "action": "accepted",
            "rationale": "البند المستشهد به يطابق الموقف المعتمد.",
        },
    )
    edited = client.post(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=seeded.scope,
        json={
            "action": "edited",
            "rationale": "The exception requires a critical negotiated cap.",
            "edited_result": "non_compliant",
            "edited_severity": "critical",
        },
    )
    history = client.get(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=seeded.scope,
    )

    assert accepted.status_code == 201
    assert edited.status_code == 201
    assert history.status_code == 200
    payload = history.json()
    assert [decision["action"] for decision in payload["events"]] == ["accepted", "edited"]
    assert [decision["original_result"] for decision in payload["events"]] == [
        "needs_review",
        "needs_review",
    ]
    assert payload["current"] == {
        "action": "edited",
        "result": "non_compliant",
        "severity": "critical",
        "rationale": "The exception requires a critical negotiated cap.",
        "actor_id": str(seeded.reviewer_id),
        "decided_at": payload["current"]["decided_at"],
    }
    evaluations = client.get(
        f"/agreements/{seeded.agreement_id}/playbook-evaluations",
        params=seeded.scope,
    )
    finding = evaluations.json()[0]["findings"][0]
    assert [decision["action"] for decision in finding["decision_events"]] == [
        "accepted",
        "edited",
    ]
    assert finding["current_decision"]["result"] == "non_compliant"
    assert finding["current_decision"]["severity"] == "critical"

    exported = client.get(
        f"/agreements/{seeded.agreement_id}/review-report",
        params=seeded.scope,
    )

    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/pdf"
    assert exported.headers["content-disposition"].startswith("attachment;")
    extracted_text = "\n".join(
        page.extract_text() for page in PdfReader(BytesIO(exported.content)).pages
    )
    for expected in (
        str(seeded.agreement_id),
        "Supplier agreement",
        "اتفاقية المورد",
        str(seeded.playbook_version_id),
        "Client baseline version 3",
        "Liability cap",
        "needs_review",
        "accepted",
        "edited",
        "non_compliant",
        "citation-liability",
        "البند المستشهد به يطابق الموقف المعتمد",
    ):
        assert expected in extracted_text

    from agreement_intelligence_api.reviews.models import (
        ReviewAuditEventRecord,
        ReviewDecisionRecord,
    )

    decisions = session.query(ReviewDecisionRecord).order_by(ReviewDecisionRecord.occurred_at).all()
    assert len(decisions) == 2
    assert decisions[0].id != decisions[1].id
    assert decisions[0].action == "accepted"
    assert decisions[1].action == "edited"
    audits = (
        session.query(ReviewAuditEventRecord).order_by(ReviewAuditEventRecord.occurred_at).all()
    )
    assert [audit.action for audit in audits] == [
        "decision_recorded",
        "decision_recorded",
        "report_exported",
    ]

    decisions[0].rationale = "mutated"
    with pytest.raises(ValueError, match="review decision events are immutable"):
        session.commit()
    session.rollback()


def test_decisions_and_exports_hide_findings_outside_authorized_scope(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_review(session)
    identity = IdentityService(session)
    other_workspace = identity.create_workspace(
        organization_id=seeded.organization_id,
        name="Disputes",
        slug=f"disputes-{uuid4()}",
    )
    session.commit()
    client = client_for_session(seeded.reviewer_id)
    wrong_scope = {
        "organization_id": str(seeded.organization_id),
        "workspace_id": str(other_workspace.id),
    }

    decision = client.post(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=wrong_scope,
        json={"action": "rejected", "rationale": "Not supported by the cited text."},
    )
    history = client.get(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=wrong_scope,
    )
    export = client.get(
        f"/agreements/{seeded.agreement_id}/review-report",
        params=wrong_scope,
    )

    assert decision.status_code == 404
    assert history.status_code == 404
    assert export.status_code == 404


def test_decision_rationale_rejects_whitespace_only_values(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_review(session)
    client = client_for_session(seeded.reviewer_id)

    response = client.post(
        f"/review-findings/{seeded.finding_id}/decisions",
        params=seeded.scope,
        json={"action": "accepted", "rationale": "   \n\t  "},
    )

    assert response.status_code == 422
    assert session.query(ReviewDecisionRecord).count() == 0


def test_database_rejects_decision_whose_workspace_does_not_match_finding(
    session: Session,
) -> None:
    seeded = _seed_review(session)
    other_workspace = IdentityService(session).create_workspace(
        organization_id=seeded.organization_id,
        name="Disputes",
        slug=f"disputes-{uuid4()}",
    )
    session.commit()
    session.add(
        ReviewDecisionRecord(
            organization_id=seeded.organization_id,
            workspace_id=other_workspace.id,
            finding_id=seeded.finding_id,
            action="accepted",
            original_result="needs_review",
            rationale="Cross-workspace corruption must fail.",
            actor_id=seeded.reviewer_id,
            occurred_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_pdf_renderer_uses_packaged_unicode_font_without_system_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_is_file = Path.is_file
    real_exists = Path.exists

    def is_packaged_temporary_font(path: Path) -> bool:
        return any(part.startswith("review-report-font-") for part in path.parts)

    monkeypatch.delenv("REVIEW_REPORT_FONT_PATH", raising=False)
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: is_packaged_temporary_font(path) and real_is_file(path),
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: is_packaged_temporary_font(path) and real_exists(path),
    )

    content = _render_pdf(["Agreement: Supplier agreement – اتفاقية المورد"])
    extracted_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)

    assert "Supplier agreement" in extracted_text
    assert "اتفاقية المورد" in extracted_text


@dataclass(frozen=True)
class _SeededReview:
    organization_id: UUID
    workspace_id: UUID
    reviewer_id: UUID
    agreement_id: UUID
    playbook_version_id: UUID
    finding_id: UUID

    @property
    def scope(self) -> dict[str, str]:
        return {
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id),
        }


class _Storage:
    def read(self, _: str) -> None:
        return None


def _seed_review(session: Session) -> _SeededReview:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    admin = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"admin-{uuid4()}",
        display_name="Administrator",
    )
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"reviewer-{uuid4()}",
        display_name="Legal Reviewer",
    )
    organization = identity.create_organization(name="Acme", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Commercial",
        slug=f"commercial-{uuid4()}",
    )
    for user_id, role_key in (
        (admin.id, RoleKey.PLATFORM_ADMIN),
        (reviewer.id, RoleKey.LEGAL_REVIEWER),
    ):
        membership = identity.grant_membership(
            organization_id=organization.id,
            user_id=user_id,
            role_key=role_key,
        )
        identity.grant_workspace_membership(
            organization_id=organization.id,
            membership_id=membership.id,
            workspace_id=workspace.id,
        )

    now = datetime.now(UTC)
    agreement = AgreementRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        title="Supplier agreement – اتفاقية المورد",
        agreement_type="client_agreement",
        status="draft",
        parties=[],
        files=[],
        processing_state="completed",
        audit_metadata={},
        audit_events=[],
        created_at=now,
        updated_at=now,
    )
    session.add(agreement)
    playbook = LegalPlaybookRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Client baseline",
        agreement_family="client_agreement",
        created_by=admin.id,
        created_at=now,
        updated_at=now,
    )
    session.add(playbook)
    session.flush()
    version = PlaybookVersionRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        playbook_id=playbook.id,
        version=3,
        status="published",
        created_by=admin.id,
        created_at=now,
        published_at=now,
    )
    session.add(version)
    session.flush()
    rule = PlaybookRuleRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        playbook_version_id=version.id,
        clause_type="limitation_of_liability",
        title="Liability cap",
        policy_type="required",
        preferred_language="Liability is capped at fees paid.",
        fallback_language=None,
        severity="high",
        legal_rationale="Exposure must be capped.",
        reviewer_guidance="Escalate uncapped liability.",
        evaluation_config={"method": "deterministic"},
        created_at=now,
        updated_at=now,
    )
    evaluation = PlaybookEvaluationRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        processing_job_id=None,
        playbook_version_id=version.id,
        analysis_version="document-analysis.v1",
        extraction_version="clause-rules.v1",
        state="completed",
        requested_by=reviewer.id,
        created_at=now,
    )
    session.add_all([rule, evaluation])
    session.flush()
    finding = PlaybookFindingRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        evaluation_id=evaluation.id,
        rule_id=rule.id,
        result="needs_review",
        severity="high",
        confidence=0.91,
        method="deterministic",
        citation_ids=["citation-liability"],
        extraction_version="clause-rules.v1",
        review_state="unreviewed",
        risk_payload={
            "version": "playbook-risk.v1",
            "severity": "high",
            "risk_rationale": "Exposure must be capped.",
            "risk_confidence": 0.91,
            "review_status": "review_required",
            "citation_ids": ["citation-liability"],
            "model_explanation": None,
        },
        fallback_suggestions=[],
    )
    session.add(finding)
    session.commit()
    return _SeededReview(
        organization_id=organization.id,
        workspace_id=workspace.id,
        reviewer_id=reviewer.id,
        agreement_id=agreement.id,
        playbook_version_id=version.id,
        finding_id=finding.id,
    )
