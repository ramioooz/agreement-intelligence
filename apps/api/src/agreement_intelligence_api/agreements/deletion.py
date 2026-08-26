import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import boto3
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import (
    AgreementDeletionOutboxRecord,
    AgreementDeletionRequestRecord,
)

logger = logging.getLogger("agreement_intelligence.api")


class AgreementDeletionQueuePublisher(Protocol):
    def publish(self, deletion: AgreementDeletionRequestRecord) -> None: ...


class UnavailableAgreementDeletionQueuePublisher:
    def publish(self, deletion: AgreementDeletionRequestRecord) -> None:
        logger.error(
            "agreement deletion queue is not configured",
            extra={
                "event": "agreement.deletion.queue_unavailable",
                "service": "api",
                "deletion_id": str(deletion.id),
            },
        )
        raise RuntimeError("agreement deletion queue is not configured")


class SQSAgreementDeletionQueuePublisher:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def publish(self, deletion: AgreementDeletionRequestRecord) -> None:
        body = json.dumps(
            {
                "message_type": "agreement_deletion",
                "deletion_id": str(deletion.id),
                "organization_id": str(deletion.organization_id),
                "workspace_id": str(deletion.workspace_id),
                "agreement_id": str(deletion.agreement_id),
            },
            sort_keys=True,
        )
        request: dict[str, object] = {"QueueUrl": self._queue_url, "MessageBody": body}
        if self._queue_url.rsplit("/", 1)[-1].endswith(".fifo"):
            request["MessageGroupId"] = str(deletion.agreement_id)
            request["MessageDeduplicationId"] = str(deletion.id)
        self._client.send_message(**request)


class AgreementDeletionOutboxDispatcher:
    def __init__(self, *, session: Session, publisher: AgreementDeletionQueuePublisher) -> None:
        self._session = session
        self._publisher = publisher

    def dispatch_pending(
        self, *, organization_id: UUID, workspace_id: UUID, limit: int = 50
    ) -> int:
        _scope_transaction(self._session, organization_id)
        pending = self._session.scalars(
            select(AgreementDeletionOutboxRecord)
            .where(AgreementDeletionOutboxRecord.organization_id == organization_id)
            .where(AgreementDeletionOutboxRecord.workspace_id == workspace_id)
            .where(AgreementDeletionOutboxRecord.delivered_at.is_(None))
            .order_by(
                AgreementDeletionOutboxRecord.created_at,
                AgreementDeletionOutboxRecord.id,
            )
            .limit(limit)
        ).all()
        delivered = 0
        for message in pending:
            deletion = message.deletion
            try:
                self._publisher.publish(deletion)
            except Exception:
                self._session.rollback()
                break
            message.delivered_at = message.updated_at = datetime.now(UTC)
            self._session.commit()
            delivered += 1
            _scope_transaction(self._session, organization_id)
        return delivered


def deletion_publisher_from_environment() -> AgreementDeletionQueuePublisher:
    queue_url = os.environ.get("SQS_PROCESSING_QUEUE")
    region = os.environ.get("AWS_REGION")
    if not queue_url or not region:
        return UnavailableAgreementDeletionQueuePublisher()
    client = boto3.client(
        "sqs",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    if "://" not in queue_url:
        queue_url = str(client.get_queue_url(QueueName=queue_url)["QueueUrl"])
    return SQSAgreementDeletionQueuePublisher(client=client, queue_url=queue_url)


def _scope_transaction(session: Session, organization_id: UUID) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
