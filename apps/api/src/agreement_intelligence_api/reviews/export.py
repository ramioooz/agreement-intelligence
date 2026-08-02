from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from unicodedata import bidirectional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from fpdf import FPDF
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.playbooks.models import PlaybookRuleRecord, PlaybookVersionRecord
from agreement_intelligence_api.reviews.decisions import decision_history_response
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
    ReviewAuditEventRecord,
)


@dataclass(frozen=True)
class ReviewReport:
    content: bytes
    filename: str


class ReviewReportService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def export(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> ReviewReport:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        agreement = self._agreement(agreement_id, organization_id, workspace_id)
        evaluation = self._evaluation(agreement_id, organization_id, workspace_id)
        version = self._version(evaluation.playbook_version_id, organization_id, workspace_id)
        generated_at = datetime.now(UTC)
        lines = _report_lines(agreement, evaluation, version, generated_at)
        content = _render_pdf(lines)
        filename = f"agreement-{agreement.id}-review-report.pdf"
        self._session.add(
            ReviewAuditEventRecord(
                id=uuid4(),
                organization_id=organization_id,
                workspace_id=workspace_id,
                action="report_exported",
                actor_id=principal.user_id,
                finding_id=None,
                agreement_id=agreement.id,
                metadata_json={
                    "evaluation_id": str(evaluation.id),
                    "playbook_version_id": str(version.id),
                },
                occurred_at=generated_at,
            )
        )
        self._session.flush()
        self._session.commit()
        return ReviewReport(content=content, filename=filename)

    def _authorize(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_DECIDE,
        ):
            hide_resource()

    def _agreement(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AgreementRecord:
        agreement = self._session.scalar(
            select(AgreementRecord)
            .where(AgreementRecord.id == agreement_id)
            .where(AgreementRecord.organization_id == organization_id)
            .where(AgreementRecord.workspace_id == workspace_id)
        )
        if agreement is None:
            hide_resource()
        return agreement

    def _evaluation(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> PlaybookEvaluationRecord:
        evaluation = self._session.scalar(
            select(PlaybookEvaluationRecord)
            .options(
                selectinload(PlaybookEvaluationRecord.findings).selectinload(
                    PlaybookFindingRecord.decisions
                )
            )
            .where(PlaybookEvaluationRecord.agreement_id == agreement_id)
            .where(PlaybookEvaluationRecord.organization_id == organization_id)
            .where(PlaybookEvaluationRecord.workspace_id == workspace_id)
            .order_by(desc(PlaybookEvaluationRecord.created_at), PlaybookEvaluationRecord.id)
        )
        if evaluation is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "completed_review_required"},
            )
        return evaluation

    def _version(
        self, version_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> PlaybookVersionRecord:
        version = self._session.scalar(
            select(PlaybookVersionRecord)
            .options(
                selectinload(PlaybookVersionRecord.playbook),
                selectinload(PlaybookVersionRecord.rules),
            )
            .where(PlaybookVersionRecord.id == version_id)
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
        )
        if version is None:
            hide_resource()
        return version


def _report_lines(
    agreement: AgreementRecord,
    evaluation: PlaybookEvaluationRecord,
    version: PlaybookVersionRecord,
    generated_at: datetime,
) -> list[str]:
    lines = [
        "Agreement Intelligence - Cited Review Report",
        f"Generated at: {generated_at.isoformat()}",
        f"Agreement: {agreement.title}",
        f"Agreement ID: {agreement.id}",
        f"Agreement type: {agreement.agreement_type}",
        f"Playbook: {version.playbook.name} version {version.version}",
        f"Playbook version ID: {version.id}",
        f"Evaluation ID: {evaluation.id}",
        f"Analysis version: {evaluation.analysis_version}",
        f"Extraction version: {evaluation.extraction_version}",
        "Findings and decisions",
    ]
    rules = {rule.id: rule for rule in version.rules}
    for index, finding in enumerate(evaluation.findings, start=1):
        rule = rules.get(finding.rule_id)
        lines.extend(_finding_lines(index, finding, rule))
    return lines


def _finding_lines(
    index: int,
    finding: PlaybookFindingRecord,
    rule: PlaybookRuleRecord | None,
) -> list[str]:
    history = decision_history_response(finding)
    lines = [
        f"Finding {index}: {rule.title if rule else finding.rule_id}",
        f"Finding ID: {finding.id}",
        f"Rule ID: {finding.rule_id}",
        f"Evaluation result: {finding.result}",
        f"Severity: {finding.severity}",
        f"Citation IDs: {', '.join(finding.citation_ids) if finding.citation_ids else 'none'}",
    ]
    for decision in history.events:
        edited = ", ".join(
            value
            for value in (
                f"result={decision.edited_result.value}" if decision.edited_result else "",
                f"severity={decision.edited_severity}" if decision.edited_severity else "",
            )
            if value
        )
        suffix = f"; edited {edited}" if edited else ""
        lines.append(
            f"Decision: {decision.action.value}; "
            f"original={decision.original_result.value}{suffix}; "
            f"actor={decision.actor_id}; at={decision.occurred_at.isoformat()}"
        )
        lines.append(f"Rationale: {decision.rationale}")
    if history.current is None:
        lines.append("Current decision: unreviewed")
    else:
        lines.append(
            f"Current decision: {history.current.action.value}; "
            f"result={history.current.result.value}; severity={history.current.severity}"
        )
    return lines


def _render_pdf(lines: list[str]) -> bytes:
    pdf = FPDF(format="letter", unit="pt")
    pdf.set_auto_page_break(auto=True, margin=36)
    pdf.add_page()
    pdf.add_font(family="ReviewReport", fname=str(_unicode_font_path()))
    pdf.set_font(family="ReviewReport", size=10)
    pdf.set_text_shaping(True)
    for line in (part for source_line in lines for part in _directional_lines(source_line)):
        pdf.multi_cell(w=0, h=14, text=line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _directional_lines(value: str) -> list[str]:
    first_rtl = next(
        (
            index
            for index, character in enumerate(value)
            if bidirectional(character) in {"R", "AL", "AN"}
        ),
        None,
    )
    if first_rtl in (None, 0):
        return [value]
    return [value[:first_rtl].rstrip(), value[first_rtl:].lstrip()]


def _unicode_font_path() -> Path:
    configured = environ.get("REVIEW_REPORT_FONT_PATH")
    candidates = (
        *([Path(configured)] if configured else []),
        Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("No Unicode review-report font is installed; set REVIEW_REPORT_FONT_PATH")
