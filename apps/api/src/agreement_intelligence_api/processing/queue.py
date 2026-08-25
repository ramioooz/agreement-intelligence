import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import boto3
from agreement_intelligence_platform.observability import (
    inject_trace_context,
    record_metric,
    safe_span_attributes,
)
from agreement_intelligence_platform.telemetry import operation_span
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agreement_intelligence_api.processing.models import ProcessingOutboxRecord
from agreement_intelligence_api.processing.schemas import ProcessingJobResponse

logger = logging.getLogger("agreement_intelligence.api")


class ProcessingQueuePublisher(Protocol):
    def publish(
        self, job: ProcessingJobResponse, *, idempotency_key: str, profile: str
    ) -> None: ...


class LoggingProcessingQueuePublisher:
    """Development fallback when no processing queue is configured."""

    def publish(self, job: ProcessingJobResponse, *, idempotency_key: str, profile: str) -> None:
        logger.info(
            "processing job queued",
            extra={
                "event": "processing.job.queued",
                "service": "api",
                "job_id": str(job.id),
            },
        )


class SQSProcessingQueuePublisher:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def publish(self, job: ProcessingJobResponse, *, idempotency_key: str, profile: str) -> None:
        payload = {
            "job_id": str(job.id),
            "organization_id": str(job.organization_id),
            "workspace_id": str(job.workspace_id),
            "agreement_id": str(job.agreement_id),
            "idempotency_key": idempotency_key,
            "profile": profile,
            "attempt_count": job.attempt_count,
            "queued_at": job.queued_at.isoformat(),
        }
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": json.dumps(payload, sort_keys=True),
        }
        trace_headers: dict[str, str] = {}
        inject_trace_context(trace_headers)
        if traceparent := trace_headers.get("traceparent"):
            request["MessageAttributes"] = {
                "traceparent": {"DataType": "String", "StringValue": traceparent}
            }
        if _is_fifo_queue(self._queue_url):
            request["MessageGroupId"] = str(job.agreement_id)
            request["MessageDeduplicationId"] = (
                f"{job.id}:{idempotency_key}:{job.attempt_count}:{job.queued_at.isoformat()}"
            )
        with operation_span(
            "agreement-intelligence.api",
            "queue.publish",
            safe_span_attributes({"operation": "queue.publish", "outcome": "success"}),
        ):
            self._client.send_message(**request)
        record_metric(
            "agreement_intelligence.operation.count",
            1,
            operation="queue.publish",
            outcome="success",
        )


class ProcessingOutboxDispatcher:
    def __init__(self, *, session: Session, publisher: ProcessingQueuePublisher) -> None:
        self._session = session
        self._publisher = publisher

    def dispatch_pending(
        self, *, organization_id: UUID, workspace_id: UUID, limit: int = 50
    ) -> int:
        _scope_transaction(self._session, organization_id)
        delivered = 0
        pending = self._session.scalars(
            select(ProcessingOutboxRecord)
            .where(ProcessingOutboxRecord.delivered_at.is_(None))
            .order_by(ProcessingOutboxRecord.created_at, ProcessingOutboxRecord.id)
            .limit(limit)
        ).all()
        for message in pending:
            try:
                self._publisher.publish(
                    _job_response_from_outbox(message),
                    idempotency_key=message.idempotency_key,
                    profile=message.profile,
                )
            except Exception:
                self._session.rollback()
                break
            message.delivered_at = message.updated_at = datetime.now(UTC)
            self._session.commit()
            delivered += 1
            _scope_transaction(self._session, organization_id)
        return delivered


def _job_response_from_outbox(message: ProcessingOutboxRecord) -> ProcessingJobResponse:
    return ProcessingJobResponse(
        id=message.job_id,
        organization_id=message.organization_id,
        workspace_id=message.workspace_id,
        agreement_id=message.agreement_id,
        state="queued",
        attempt_count=message.attempt_count,
        failure_category=None,
        failure_message=None,
        next_retry_at=None,
        queued_at=message.queued_at,
        processing_started_at=None,
        completed_at=None,
        failed_at=None,
        created_at=message.created_at,
        updated_at=message.updated_at,
        retry_permitted=False,
    )


def _is_fifo_queue(queue_url: str) -> bool:
    return queue_url.rsplit("/", 1)[-1].endswith(".fifo")


def _scope_transaction(session: Session, organization_id: UUID) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )


def queue_publisher_from_environment() -> ProcessingQueuePublisher:
    queue_url = os.environ.get("SQS_PROCESSING_QUEUE")
    region = os.environ.get("AWS_REGION")
    if not queue_url or not region:
        return LoggingProcessingQueuePublisher()
    client = boto3.client(
        "sqs",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    return SQSProcessingQueuePublisher(
        client=client,
        queue_url=_resolve_queue_url(client, queue_url),
    )


def _resolve_queue_url(client: Any, configured_queue: str) -> str:
    if "://" in configured_queue:
        return configured_queue
    return str(client.get_queue_url(QueueName=configured_queue)["QueueUrl"])
