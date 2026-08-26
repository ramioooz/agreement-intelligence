from uuid import UUID

from sqlalchemy import Select, select

from agreement_intelligence_api.agreements.models import AgreementRecord


def active_agreement_statement(
    agreement_id: UUID,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    for_update: bool = False,
) -> Select[tuple[AgreementRecord]]:
    """The single boundary for loading user-visible, mutable agreement state."""
    statement = select(AgreementRecord).where(
        AgreementRecord.id == agreement_id,
        AgreementRecord.organization_id == organization_id,
        AgreementRecord.workspace_id == workspace_id,
        AgreementRecord.deletion_requested_at.is_(None),
    )
    return statement.with_for_update() if for_update else statement


def active_agreement_condition() -> object:
    """Condition for queries that already join ``AgreementRecord``."""
    return AgreementRecord.deletion_requested_at.is_(None)
