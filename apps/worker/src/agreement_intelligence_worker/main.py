import asyncio
import os
import signal
from dataclasses import dataclass

import boto3

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
    CompletionHandlerFanout,
    JobProcessor,
    SQLAlchemyProcessingJobRepository,
    SQSProcessingMessageReceiver,
    SQSProcessingQueue,
    processing_engine_from_url,
)


@dataclass(frozen=True)
class ProcessingRuntime:
    receiver: SQSProcessingMessageReceiver
    processor: JobProcessor


async def serve() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    runtime = processing_runtime_from_environment()
    if runtime is None:
        await run_worker(stop_event)
        return
    await run_worker(
        stop_event,
        message_receiver=runtime.receiver,
        job_processor=runtime.processor,
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
        DocumentUnderstandingProcessor(
            storage,
            analysis_provider=provider_from_environment(),
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


def main() -> None:
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
