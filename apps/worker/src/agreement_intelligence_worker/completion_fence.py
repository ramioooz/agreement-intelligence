"""Agreement fence shared by completion-derived database writers."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def lock_active_agreement(
    connection: Connection,
    *,
    agreement_id: UUID,
    organization_id: UUID | None,
    workspace_id: UUID | None,
) -> bool:
    """Lock the owning agreement before derived rows and reject accepted deletion."""
    if connection.dialect.name != "postgresql":
        return True
    if organization_id is None or workspace_id is None:
        return False
    return (
        connection.scalar(
            text(
                """
                SELECT id FROM agreements
                WHERE id=:agreement_id
                  AND organization_id=:organization_id
                  AND workspace_id=:workspace_id
                  AND deletion_requested_at IS NULL
                FOR UPDATE
                """
            ),
            {
                "agreement_id": agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
            },
        )
        is not None
    )
