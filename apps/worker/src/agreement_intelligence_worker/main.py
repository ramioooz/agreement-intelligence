import asyncio
import os
import signal
from dataclasses import dataclass
from typing import Any, cast

import boto3
from agreement_intelligence_platform.telemetry import configure_telemetry

from agreement_intelligence_worker.agreement_deletion import (
    AgreementDeletionOutboxSweeper,
    AgreementDeletionProcessor,
    SQLAlchemyAgreementDeletionRepository,
    run_deletion_outbox_loop,
)
from agreement_intelligence_worker.analysis_provider import (
    fallback_comparator_from_environment,
    provider_from_environment,
)
from agreement_intelligence_worker.artifact_commit import PreparedArtifact
from agreement_intelligence_worker.document_indexing import SQLAlchemyDocumentIndexSink
from agreement_intelligence_worker.document_processor import (
    DocumentUnderstandingProcessor,
    S3ObjectStorage,
)
from agreement_intelligence_worker.embedding_indexing import (
    EmbeddingReindexCompletionHandler,
    SQLAlchemyEmbeddingIndexSink,
    embedding_reindex_configuration_id,
)
from agreement_intelligence_worker.final_package import (
    S3FinalPackageStorage,
    TerminalReviewPackageGenerator,
)
from agreement_intelligence_worker.lifecycle import run_worker
from agreement_intelligence_worker.logging_config import configure_logging
from agreement_intelligence_worker.model_gateway import (
    embedding_configuration_from_environment,
    embedding_gateway_from_environment,
    model_gateway_from_environment,
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

    def expected_artifact(self, job: ProcessingJob) -> CompletedArtifact:
        if job.profile == "version-comparison":
            return self._comparison.expected_artifact(job)
        configuration_id = embedding_reindex_configuration_id(job.profile)
        if configuration_id is not None:
            return CompletedArtifact(
                job_id=job.id,
                key=f"embedding-reindex/{configuration_id}.json",
            )
        return self._document.expected_artifact(job)

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        if job.profile == "version-comparison":
            legacy = getattr(self._comparison, "process", None)
            if callable(legacy):
                return cast(CompletedArtifact, legacy(job))
            return self._comparison.prepare(job).artifact
        configuration_id = embedding_reindex_configuration_id(job.profile)
        if configuration_id is not None:
            return self.expected_artifact(job)
        return self._document.process(job)

    def prepare(self, job: ProcessingJob) -> PreparedArtifact:
        if job.profile == "version-comparison":
            return self._comparison.prepare(job)
        configuration_id = embedding_reindex_configuration_id(job.profile)
        if configuration_id is not None:
            return PreparedArtifact(
                artifact=self.expected_artifact(job),
                content=None,
                content_type=None,
            )
        return self._document.prepare(job)

    def finalize(
        self,
        connection: Any,
        job: ProcessingJob,
        prepared: PreparedArtifact,
        canonical_content: bytes | None,
    ) -> None:
        if job.profile == "version-comparison":
            self._comparison.finalize(connection, job, prepared, canonical_content)
        elif embedding_reindex_configuration_id(job.profile) is None:
            self._document.finalize(connection, job, prepared, canonical_content)

    def discard(self, artifact: CompletedArtifact) -> None:
        if artifact.key.startswith("comparisons/"):
            self._comparison.discard(artifact)
        elif not artifact.key.startswith("embedding-reindex/"):
            self._document.discard(artifact)


@dataclass(frozen=True)
class ProcessingRuntime:
    receiver: SQSProcessingMessageReceiver
    processor: JobProcessor
    deletion_processor: AgreementDeletionProcessor
    deletion_outbox_sweeper: AgreementDeletionOutboxSweeper


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
    outbox_sweeper = getattr(runtime, "deletion_outbox_sweeper", None)
    outbox_tasks = (
        (run_deletion_outbox_loop(stop_event, outbox_sweeper),)
        if outbox_sweeper is not None
        else ()
    )
    if workflow_runtime is None:
        await run_worker(
            stop_event,
            message_receiver=runtime.receiver,
            job_processor=runtime.processor,
            deletion_processor=getattr(runtime, "deletion_processor", None),
            background_tasks=outbox_tasks,
        )
    else:
        await run_worker(
            stop_event,
            message_receiver=runtime.receiver,
            job_processor=runtime.processor,
            deletion_processor=getattr(runtime, "deletion_processor", None),
            background_tasks=(
                *outbox_tasks,
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
    document_client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
        region_name=region,
    )
    storage = S3ObjectStorage(client=document_client, bucket=bucket)
    repository = SQLAlchemyProcessingJobRepository(engine, storage=storage)
    embedding_configuration = embedding_configuration_from_environment()
    model_gateway = model_gateway_from_environment()
    embedding_sink = SQLAlchemyEmbeddingIndexSink(
        engine,
        gateway=embedding_gateway_from_environment(),
        configuration=embedding_configuration,
    )
    processor = JobProcessor(
        repository,
        queue,
        ProfileProcessor(
            DocumentUnderstandingProcessor(storage, analysis_provider=provider_from_environment()),
            VersionComparisonProcessor(database_url, storage, gateway=model_gateway),
        ),
        completion_handler=EmbeddingReindexCompletionHandler(
            normal=CompletionHandlerFanout(
                handlers=(
                    SQLAlchemyPlaybookEvaluationSink(
                        engine,
                        storage,
                        fallback_model_comparator=fallback_comparator_from_environment(),
                    ),
                    SQLAlchemyDocumentIndexSink(engine, storage),
                    embedding_sink,
                )
            ),
            embeddings=embedding_sink,
        ),
    )
    receiver = SQSProcessingMessageReceiver(client=client, queue_url=queue_url)
    deletion_repository = SQLAlchemyAgreementDeletionRepository(engine)
    return ProcessingRuntime(
        receiver=receiver,
        processor=processor,
        deletion_processor=AgreementDeletionProcessor(
            deletion_repository,
            storage,
        ),
        deletion_outbox_sweeper=AgreementDeletionOutboxSweeper(
            deletion_repository,
            queue,
        ),
    )


def workflow_runtime_from_environment() -> WorkflowRuntime | None:
    queue_url = os.environ.get("SQS_NOTIFICATION_QUEUE")
    region = os.environ.get("AWS_REGION")
    database_url = os.environ.get("DATABASE_URL")
    bucket = os.environ.get("S3_DOCUMENT_BUCKET")
    if not queue_url:
        return None
    if not region or not database_url or not bucket:
        raise RuntimeError(
            "AWS_REGION, DATABASE_URL, and S3_DOCUMENT_BUCKET are required "
            "for review workflow runtime"
        )
    queue_client = boto3.client(
        "sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"), region_name=region
    )
    if "://" not in queue_url:
        queue_url = str(queue_client.get_queue_url(QueueName=queue_url)["QueueUrl"])
    storage_client = boto3.client(
        "s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"), region_name=region
    )
    engine = processing_engine_from_url(database_url)
    checkpoints = PostgresWorkflowCheckpointStore(database_url)
    packages = TerminalReviewPackageGenerator(
        S3FinalPackageStorage(client=storage_client, bucket=bucket)
    )
    return WorkflowRuntime(
        receiver=SQSWorkflowMessageReceiver(client=queue_client, queue_url=queue_url),
        processor=SQLAlchemyWorkflowEventProcessor(
            engine,
            checkpoints,
            packages,
        ),
    )


def main() -> None:
    configure_telemetry("agreement-intelligence-worker", environment=os.environ)
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
