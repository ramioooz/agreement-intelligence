"""Durable object-write boundary shared by final-package producers."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.reviews.models import (
    ReviewCaseRecord,
    ReviewFinalPackageRecord,
    ReviewWorkflowRecord,
)
from agreement_intelligence_api.reviews.workflow import (
    _scope_transaction as _workflow_scope_transaction,
)

TERMINAL_WORKFLOW_STATES = {"approved", "rejected", "revision_requested"}


def _scope_transaction(session: Session, organization_id: UUID) -> None:
    _workflow_scope_transaction(session, organization_id)


def active_final_package_workflow_for_update(
    review_id: UUID,
) -> Select[tuple[ReviewWorkflowRecord]]:
    """Lock the workflow and owning agreement while rejecting accepted deletion."""
    return (
        select(ReviewWorkflowRecord)
        .join(ReviewCaseRecord, ReviewWorkflowRecord.review_id == ReviewCaseRecord.id)
        .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
        .where(ReviewWorkflowRecord.review_id == review_id)
        .where(AgreementRecord.deletion_requested_at.is_(None))
        .with_for_update(of=(ReviewWorkflowRecord, AgreementRecord))
    )


def reserve_final_package_intent(
    session: Session,
    *,
    review: ReviewCaseRecord,
    workflow: ReviewWorkflowRecord,
    manifest_key: str,
    pdf_key: str,
    manifest_checksum: str,
    pdf_checksum: str,
) -> ReviewFinalPackageRecord:
    """Commit deterministic keys and return with the active-agreement fence held."""
    review_id = review.id
    organization_id = review.organization_id
    workspace_id = review.workspace_id
    locked = session.scalar(active_final_package_workflow_for_update(review_id))
    if locked is None or locked.state not in TERMINAL_WORKFLOW_STATES:
        raise HTTPException(status_code=409, detail="final_package_not_ready")
    existing = session.scalar(
        select(ReviewFinalPackageRecord).where(
            ReviewFinalPackageRecord.review_id == review_id,
            ReviewFinalPackageRecord.organization_id == organization_id,
            ReviewFinalPackageRecord.workspace_id == workspace_id,
        )
    )
    if existing is not None:
        expected = (
            workflow.id,
            workflow.state,
            manifest_key,
            pdf_key,
            manifest_checksum,
            pdf_checksum,
        )
        recorded = (
            existing.workflow_id,
            existing.state,
            existing.manifest_key,
            existing.pdf_key,
            existing.manifest_checksum,
            existing.pdf_checksum,
        )
        if recorded != expected:
            raise HTTPException(status_code=409, detail="final_package_intent_conflict")
        return existing
    package = ReviewFinalPackageRecord(
        organization_id=organization_id,
        workspace_id=workspace_id,
        review_id=review_id,
        workflow_id=workflow.id,
        state=workflow.state,
        manifest_key=manifest_key,
        pdf_key=pdf_key,
        manifest_checksum=manifest_checksum,
        pdf_checksum=pdf_checksum,
    )
    session.add(package)
    session.commit()
    _scope_transaction(session, organization_id)
    if session.scalar(active_final_package_workflow_for_update(review_id)) is None:
        raise HTTPException(status_code=409, detail="final_package_not_ready")
    return package
