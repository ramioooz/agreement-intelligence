from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Float,
    MetaData,
    String,
    Table,
    Uuid,
    select,
    text,
)

EvaluationMethod = Literal["deterministic", "semantic"]
PolicyType = Literal["required", "prohibited", "preferred"]

_MINIMUM_CONFIDENCE = 0.8
worker_evaluation_metadata = MetaData()
agreements = Table(
    "agreements",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_type", String(100), nullable=False),
)
legal_playbooks = Table(
    "legal_playbooks",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_family", String(100), nullable=False),
)
playbook_versions = Table(
    "playbook_versions",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("playbook_id", Uuid(as_uuid=True), nullable=False),
    Column("status", String(16), nullable=False),
)
playbook_rules = Table(
    "playbook_rules",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("playbook_version_id", Uuid(as_uuid=True), nullable=False),
    Column("clause_type", String(128), nullable=False),
    Column("policy_type", String(16), nullable=False),
    Column("preferred_language", String(), nullable=True),
    Column("severity", String(16), nullable=False),
    Column("evaluation_config", JSON, nullable=False),
)
playbook_evaluations = Table(
    "playbook_evaluations",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("playbook_version_id", Uuid(as_uuid=True), nullable=False),
    Column("analysis_version", String(100), nullable=False),
    Column("extraction_version", String(100), nullable=False),
    Column("state", String(32), nullable=False),
    Column("requested_by", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
playbook_findings = Table(
    "playbook_findings",
    worker_evaluation_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("evaluation_id", Uuid(as_uuid=True), nullable=False),
    Column("rule_id", Uuid(as_uuid=True), nullable=False),
    Column("result", String(32), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("method", String(16), nullable=False),
    Column("citation_ids", JSON, nullable=False),
    Column("extraction_version", String(100), nullable=False),
    Column("review_state", String(32), nullable=False),
)


class FindingResult(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PlaybookRule:
    id: str
    clause_type: str
    policy_type: PolicyType
    preferred_language: str | None
    severity: str
    evaluation_method: EvaluationMethod = "deterministic"
    semantic_assessment_permitted: bool = False


@dataclass(frozen=True)
class EvaluatedFinding:
    rule_id: str
    result: FindingResult
    severity: str
    confidence: float
    method: EvaluationMethod
    citation_ids: list[str]
    extraction_version: str


SemanticAssessor = Callable[[PlaybookRule, Mapping[str, object]], FindingResult]


def evaluate_playbook(
    rules: Iterable[PlaybookRule],
    analysis: Mapping[str, object],
    *,
    semantic_assessor: SemanticAssessor | None = None,
) -> list[EvaluatedFinding]:
    """Evaluate extracted clauses deterministically before optional semantic assessment.

    An extraction is evidence only when it has a citation and meets the confidence
    floor. Missing or uncertain evidence remains explicitly reviewable.
    """
    clauses = _clauses(analysis)
    findings: list[EvaluatedFinding] = []
    for rule in rules:
        candidates = [
            clause
            for clause in clauses
            if _normalized(clause.get("category")) == _normalized(rule.clause_type)
        ]
        finding, selected_clause = _deterministic_finding(rule, candidates)
        if _may_assess_semantically(rule, finding, selected_clause, semantic_assessor):
            assert semantic_assessor is not None
            assert selected_clause is not None
            semantic_result = semantic_assessor(rule, selected_clause)
            # Model assistance can flag ambiguity/deviation but cannot create compliance.
            if semantic_result in {FindingResult.NEEDS_REVIEW, FindingResult.NON_COMPLIANT}:
                finding = EvaluatedFinding(
                    rule_id=finding.rule_id,
                    result=semantic_result,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    method="semantic",
                    citation_ids=finding.citation_ids,
                    extraction_version=finding.extraction_version,
                )
        findings.append(finding)
    return findings


def _deterministic_finding(
    rule: PlaybookRule, candidates: list[Mapping[str, object]]
) -> tuple[EvaluatedFinding, Mapping[str, object] | None]:
    if not candidates:
        return _finding(rule, FindingResult.NEEDS_REVIEW, 0.0, [], "unknown"), None
    clause = max(candidates, key=_confidence)
    confidence = _confidence(clause)
    citations = _citations(clause)
    extraction_version = _string(clause.get("extraction_version"), "unknown")
    if confidence < _MINIMUM_CONFIDENCE or not citations:
        return (
            _finding(rule, FindingResult.NEEDS_REVIEW, confidence, citations, extraction_version),
            clause,
        )

    source_text = _string(clause.get("source_text"), "").casefold()
    expected_language = (rule.preferred_language or "").strip().casefold()
    if not expected_language:
        return (
            _finding(rule, FindingResult.NEEDS_REVIEW, confidence, citations, extraction_version),
            clause,
        )
    matches_policy_language = bool(expected_language) and expected_language in source_text
    if rule.policy_type == "prohibited":
        result = FindingResult.NON_COMPLIANT if matches_policy_language else FindingResult.SATISFIED
    elif matches_policy_language:
        result = FindingResult.SATISFIED
    else:
        result = FindingResult.NEEDS_REVIEW
    return _finding(rule, result, confidence, citations, extraction_version), clause


def _may_assess_semantically(
    rule: PlaybookRule,
    finding: EvaluatedFinding,
    selected_clause: Mapping[str, object] | None,
    semantic_assessor: SemanticAssessor | None,
) -> bool:
    return (
        semantic_assessor is not None
        and rule.evaluation_method == "semantic"
        and rule.semantic_assessment_permitted
        and finding.result is FindingResult.NEEDS_REVIEW
        and selected_clause is not None
        and bool(finding.citation_ids)
        and finding.confidence >= _MINIMUM_CONFIDENCE
    )


def _finding(
    rule: PlaybookRule,
    result: FindingResult,
    confidence: float,
    citation_ids: list[str],
    extraction_version: str,
) -> EvaluatedFinding:
    return EvaluatedFinding(
        rule_id=rule.id,
        result=result,
        severity=rule.severity,
        confidence=confidence,
        method="deterministic",
        citation_ids=citation_ids,
        extraction_version=extraction_version,
    )


def _clauses(analysis: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = analysis.get("clauses", [])
    if not isinstance(value, list):
        return []
    return [clause for clause in value if isinstance(clause, Mapping)]


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _string(value, "").casefold()).strip("_")


def _confidence(clause: Mapping[str, object]) -> float:
    value = clause.get("confidence")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _citations(clause: Mapping[str, object]) -> list[str]:
    value = clause.get("citation_anchor_ids")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


class SQLAlchemyPlaybookEvaluationSink:
    """Select and persist deterministic findings after an immutable analysis exists."""

    def __init__(self, engine: Engine, storage: object) -> None:
        self._engine = engine
        self._storage = storage

    def completed(self, job: object, artifact: object) -> None:
        from agreement_intelligence_worker.processing import ProcessingJob

        if not isinstance(job, ProcessingJob):
            raise TypeError("playbook evaluation requires a processing job")
        if job.organization_id is None or job.workspace_id is None:
            return
        artifact_key = getattr(artifact, "key", None)
        reader = getattr(self._storage, "read", None)
        if not isinstance(artifact_key, str) or not callable(reader):
            return
        content = reader(artifact_key)
        if not isinstance(content, bytes):
            return
        try:
            manifest = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(manifest, dict):
            return
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(job.organization_id)},
                )
            agreement = (
                connection.execute(
                    select(agreements.c.agreement_type)
                    .where(agreements.c.id == job.agreement_id)
                    .where(agreements.c.organization_id == job.organization_id)
                    .where(agreements.c.workspace_id == job.workspace_id)
                )
                .mappings()
                .one_or_none()
            )
            if agreement is None:
                return
            version = (
                connection.execute(
                    select(playbook_versions.c.id)
                    .join(legal_playbooks, playbook_versions.c.playbook_id == legal_playbooks.c.id)
                    .where(playbook_versions.c.organization_id == job.organization_id)
                    .where(playbook_versions.c.workspace_id == job.workspace_id)
                    .where(playbook_versions.c.status == "published")
                    .where(legal_playbooks.c.organization_id == job.organization_id)
                    .where(legal_playbooks.c.workspace_id == job.workspace_id)
                    .where(legal_playbooks.c.agreement_family == agreement["agreement_type"])
                    .order_by(playbook_versions.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if version is None:
                return
            rule_rows = list(
                connection.execute(
                    select(playbook_rules)
                    .where(playbook_rules.c.organization_id == job.organization_id)
                    .where(playbook_rules.c.workspace_id == job.workspace_id)
                    .where(playbook_rules.c.playbook_version_id == version["id"])
                    .order_by(playbook_rules.c.id)
                ).mappings()
            )
            rules = [
                PlaybookRule(
                    id=str(row["id"]),
                    clause_type=str(row["clause_type"]),
                    policy_type=_policy_type(row["policy_type"]),
                    preferred_language=_optional_string(row["preferred_language"]),
                    severity=str(row["severity"]),
                    evaluation_method=_evaluation_method(row["evaluation_config"]),
                    semantic_assessment_permitted=_semantic_permitted(row["evaluation_config"]),
                )
                for row in rule_rows
            ]
            findings = evaluate_playbook(rules, manifest)
            extraction_version = next(
                (
                    finding.extraction_version
                    for finding in findings
                    if finding.extraction_version != "unknown"
                ),
                "unknown",
            )
            evaluation_id = uuid4()
            connection.execute(
                playbook_evaluations.insert().values(
                    id=evaluation_id,
                    organization_id=job.organization_id,
                    workspace_id=job.workspace_id,
                    agreement_id=job.agreement_id,
                    playbook_version_id=version["id"],
                    analysis_version=_string(manifest.get("schema_version"), "unknown"),
                    extraction_version=extraction_version,
                    state="completed",
                    requested_by=None,
                    created_at=datetime.now(UTC),
                )
            )
            rules_by_id = {str(row["id"]): row for row in rule_rows}
            connection.execute(
                playbook_findings.insert(),
                [
                    {
                        "id": uuid4(),
                        "organization_id": job.organization_id,
                        "workspace_id": job.workspace_id,
                        "evaluation_id": evaluation_id,
                        "rule_id": rules_by_id[finding.rule_id]["id"],
                        "result": finding.result.value,
                        "severity": finding.severity,
                        "confidence": finding.confidence,
                        "method": finding.method,
                        "citation_ids": finding.citation_ids,
                        "extraction_version": finding.extraction_version,
                        "review_state": "unreviewed",
                    }
                    for finding in findings
                ],
            )


def _policy_type(value: object) -> PolicyType:
    return value if value in {"required", "prohibited", "preferred"} else "required"


def _evaluation_method(value: object) -> EvaluationMethod:
    if isinstance(value, dict) and value.get("method") == "semantic":
        return "semantic"
    return "deterministic"


def _semantic_permitted(value: object) -> bool:
    return isinstance(value, dict) and value.get("semantic_assessment_permitted") is True


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
