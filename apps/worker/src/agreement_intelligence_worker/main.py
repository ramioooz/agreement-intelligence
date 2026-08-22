import asyncio
import os
import signal
from dataclasses import dataclass

import boto3
from agreement_intelligence_platform.telemetry import configure_telemetry

from agreement_intelligence_worker.analysis_provider import (
    fallback_comparator_from_environment,
    provider_from_environment,
)
from agreement_intelligence_worker.document_indexing import SQLAlchemyDocumentIndexSink
from agreement_intelligence_worker.document_processor import (
    DocumentUnderstandingProcessor,
    S3ObjectStorage,
)
from agreement_intelligence_worker.embedding_indexing import SQLAlchemyEmbeddingIndexSink
from agreement_intelligence_worker.lifecycle import run_worker
from agreement_intelligence_worker.logging_config import configure_logging
from agreement_intelligence_worker.model_gateway import (
    embedding_configuration_from_environment,
    embedding_gateway_from_environment,
)
from agreement_intelligence_worker.playbook_evaluation import SQLAlchemyPlaybookEvaluationSink
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    CompletionHandlerFanout,
    JobProcessor,
    ProcessingJob,
    SQLAlchemyProcessingJobRepository,
    SQSProcessingMessageReceiver,
    SQSProcessingQueue,
    processing_engine_from_url,
)
from agreement_intelligence_worker.review_workflow import (
    PostgresWorkflowCheckpointStore,
    SQLAlchemyWorkflowEventProcessor,
    SQSWorkflowMessageReceiver,
    run_workflow_loop,
)
from agreement_intelligence_worker.version_comparison_processor import VersionComparisonProcessor


class ProfileProcessor:
    """Keeps document and comparison work on one durable queue without conflating contracts."""

    def __init__(
        self, document: DocumentUnderstandingProcessor, comparison: VersionComparisonProcessor
    ) -> None:
        self._document = document
        self._comparison = comparison

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        if job.profile == "version-comparison":
            return self._comparison.process(job)
        return self._document.process(job)


@dataclass(frozen=True)
class ProcessingRuntime:
    receiver: SQSProcessingMessageReceiver
    processor: JobProcessor


@dataclass(frozen=True)
class WorkflowRuntime:
    receiver: SQSWorkflowMessageReceiver
    processor: SQLAlchemyWorkflowEventProcessor


async def serve() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    runtime = processing_runtime_from_environment()
    workflow_runtime = workflow_runtime_from_environment()
    if runtime is None:
        if workflow_runtime is None:
            await run_worker(stop_event)
        else:
            await run_worker(
                stop_event,
                background_tasks=(
                    run_workflow_loop(
                        stop_event, workflow_runtime.receiver, workflow_runtime.processor
                    ),
                ),
            )
        return
    if workflow_runtime is None:
        await run_worker(
            stop_event,
            message_receiver=runtime.receiver,
            job_processor=runtime.processor,
        )
    else:
        await run_worker(
            stop_event,
            message_receiver=runtime.receiver,
            job_processor=runtime.processor,
            background_tasks=(
                run_workflow_loop(
                    stop_event, workflow_runtime.receiver, workflow_runtime.processor
                ),
            ),
        )


def processing_runtime_from_environment() -> ProcessingRuntime | None:
    queue_url = os.environ.get("SQS_PROCESSING_QUEUE")
    if not queue_url:
        return None
    region = os.environ.get("AWS_REGION")
    database_url = os.environ.get("DATABASE_URL")
    bucket = os.environ.get("S3_DOCUMENT_BUCKET")
    if not region or not database_url or not bucket:
        raise RuntimeError(
            "AWS_REGION, DATABASE_URL, and S3_DOCUMENT_BUCKET are required "
            "for processing worker runtime"
        )
    client = boto3.client(
        "sqs",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    if "://" not in queue_url:
        queue_url = str(client.get_queue_url(QueueName=queue_url)["QueueUrl"])
    engine = processing_engine_from_url(database_url)
    queue = SQSProcessingQueue(client=client, queue_url=queue_url)
    repository = SQLAlchemyProcessingJobRepository(engine)
    document_client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    storage = S3ObjectStorage(client=document_client, bucket=bucket)
    embedding_configuration = embedding_configuration_from_environment()
    processor = JobProcessor(
        repository,
        queue,
        ProfileProcessor(
            DocumentUnderstandingProcessor(storage, analysis_provider=provider_from_environment()),
            VersionComparisonProcessor(database_url, storage),
        ),
        completion_handler=CompletionHandlerFanout(
            handlers=(
                SQLAlchemyPlaybookEvaluationSink(
                    engine,
                    storage,
                    fallback_model_comparator=fallback_comparator_from_environment(),
                ),
                SQLAlchemyDocumentIndexSink(engine, storage),
                SQLAlchemyEmbeddingIndexSink(
                    engine,
                    gateway=embedding_gateway_from_environment(),
                    configuration=embedding_configuration,
                ),
            )
        ),
    )
    receiver = SQSProcessingMessageReceiver(client=client, queue_url=queue_url)
    return ProcessingRuntime(receiver=receiver, processor=processor)


def workflow_runtime_from_environment() -> WorkflowRuntime | None:
    queue_url = os.environ.get("SQS_NOTIFICATION_QUEUE")
    region = os.environ.get("AWS_REGION")
    database_url = os.environ.get("DATABASE_URL")
    if not queue_url:
        return None
    if not region or not database_url:
        raise RuntimeError("AWS_REGION and DATABASE_URL are required for review workflow runtime")
    client = boto3.client(
        "sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"), region_name=region
    )
    if "://" not in queue_url:
        queue_url = str(client.get_queue_url(QueueName=queue_url)["QueueUrl"])
    return WorkflowRuntime(
        receiver=SQSWorkflowMessageReceiver(client=client, queue_url=queue_url),
        processor=SQLAlchemyWorkflowEventProcessor(
            processing_engine_from_url(database_url),
            PostgresWorkflowCheckpointStore(database_url),
        ),
    )


def main() -> None:
    configure_telemetry("agreement-intelligence-worker", environment=os.environ)
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
