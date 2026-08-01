from __future__ import annotations

import json
from uuid import uuid4

from agreement_intelligence_worker.playbook_evaluation import (
    SQLAlchemyPlaybookEvaluationSink,
    worker_evaluation_metadata,
)
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob
from sqlalchemy import create_engine, select


def test_sink_selects_a_published_same_family_playbook_and_persists_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_evaluation_metadata.create_all(engine)
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    playbook_id = uuid4()
    version_id = uuid4()
    rule_id = uuid4()
    job = ProcessingJob(
        id=uuid4(),
        agreement_id=agreement_id,
        state="processing",
        attempt_count=1,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    with engine.begin() as connection:
        connection.execute(
            worker_evaluation_metadata.tables["agreements"]
            .insert()
            .values(
                id=agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_type="client_agreement",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["legal_playbooks"]
            .insert()
            .values(
                id=playbook_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_family="client_agreement",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["playbook_versions"]
            .insert()
            .values(
                id=version_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                playbook_id=playbook_id,
                status="published",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["playbook_rules"]
            .insert()
            .values(
                id=rule_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                playbook_version_id=version_id,
                clause_type="limitation_of_liability",
                policy_type="prohibited",
                preferred_language="unlimited liability",
                fallback_language="Liability is capped at USD 100,000.",
                severity="critical",
                evaluation_config={"method": "deterministic"},
            )
        )

    manifest = {
        "schema_version": "document-analysis.v1",
        "clauses": [
            {
                "category": "limitation_of_liability",
                "source_text": "The supplier accepts unlimited liability.",
                "confidence": 0.91,
                "citation_anchor_ids": ["citation-liability"],
                "extraction_version": "clause-rules.v1",
            }
        ],
    }

    class Storage:
        def read(self, key: str) -> bytes | None:
            assert key == "analysis/manifest.json"
            return json.dumps(manifest).encode()

    sink = SQLAlchemyPlaybookEvaluationSink(
        engine,
        Storage(),
        risk_model_explainer=lambda _: {
            "rationale": "The cited clause accepts unlimited liability.",
            "citation_ids": ["citation-liability"],
        },
        fallback_model_comparator=lambda _: {
            "comparison": "This must not be persisted.",
            "citation_ids": ["citation-not-in-evidence"],
        },
    )
    artifact = CompletedArtifact(job_id=job.id, key="analysis/manifest.json")
    sink.completed(
        job,
        artifact,
    )
    sink.completed(job, artifact)

    with engine.connect() as connection:
        evaluation = (
            connection.execute(select(worker_evaluation_metadata.tables["playbook_evaluations"]))
            .mappings()
            .one()
        )
        finding = (
            connection.execute(select(worker_evaluation_metadata.tables["playbook_findings"]))
            .mappings()
            .one()
        )

    assert evaluation["organization_id"] == organization_id
    assert evaluation["workspace_id"] == workspace_id
    assert evaluation["agreement_id"] == agreement_id
    assert evaluation["processing_job_id"] == job.id
    assert evaluation["playbook_version_id"] == version_id
    assert evaluation["analysis_version"] == "document-analysis.v1"
    assert evaluation["extraction_version"] == "clause-rules.v1"
    assert finding["rule_id"] == rule_id
    assert finding["result"] == "non_compliant"
    assert finding["citation_ids"] == ["citation-liability"]
    assert finding["risk_payload"] == {
        "version": "playbook-risk.v1",
        "severity": "critical",
        "risk_rationale": "The deterministic finding requires reviewer assessment.",
        "risk_confidence": 0.91,
        "review_status": "review_required",
        "citation_ids": ["citation-liability"],
        "model_explanation": "The cited clause accepts unlimited liability.",
    }
    assert finding["fallback_suggestions"] == [
        {
            "version": "playbook-fallback-suggestion.v1",
            "rule_id": str(rule_id),
            "playbook_version_id": str(version_id),
            "suggested_language": "Liability is capped at USD 100,000.",
            "review_recommendation": (
                "Review the cited clause against the approved fallback language."
            ),
            "citation_ids": ["citation-liability"],
            "comparison_kind": None,
            "comparison": None,
            "ai_generated": False,
        }
    ]
