from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast
from uuid import uuid4

import boto3
from agreement_intelligence_worker.analysis_provider import ProviderAnalysis
from agreement_intelligence_worker.document_processor import DocumentUnderstandingProcessor
from agreement_intelligence_worker.model_gateway import GatewayProvenance
from agreement_intelligence_worker.processing import ProcessingJob, TransientProcessingError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from pytest import MonkeyPatch, raises


@dataclass
class InMemoryObjectStorage:
    objects: dict[str, bytes]

    def read(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = content
        return True


class FakeProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        return _valid_provider_response(blocks[0][0])


class ProvenancedProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        response = _valid_provider_response(blocks[0][0])
        return ProviderAnalysis(
            **{
                **response.__dict__,
                "gateway_provenance": GatewayProvenance(
                    provider="openai-compatible",
                    endpoint_kind="openai-compatible",
                    model="local-model.gguf",
                    configuration_version="model-gateway.v1",
                    latency_ms=42,
                    input_tokens=10,
                    output_tokens=20,
                    total_tokens=30,
                    cost_usd=None,
                    retry_outcome="not_retried",
                    fallback_outcome="hosted_fallback_succeeded",
                    safe_failure_reason="compatible_endpoint_unavailable",
                ),
            }
        )


class FailingProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        raise RuntimeError("hosted provider unavailable")


class InvalidProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        return _valid_provider_response("citation-not-from-this-document")


class TimeoutProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        raise TimeoutError("provider request timed out")


def test_processor_writes_a_versioned_cited_document_analysis_manifest() -> None:
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage)

    artifact = processor.process(job)
    manifest = json.loads(storage.objects[artifact.key])

    assert artifact.key == (
        f"tenants/{job.organization_id}/workspaces/{job.workspace_id}/"
        f"agreements/{job.agreement_id}/"
        f"analysis/{'a' * 64}/document-analysis.v1.json"
    )
    assert manifest["schema_version"] == "document-analysis.v1"
    assert manifest["source"]["checksum"] == "a" * 64
    assert manifest["document"]["pages"][0]["blocks"][0]["text"] == "Client Agreement"
    assert manifest["citations"][0]["anchor_id"].startswith("citation-")
    assert manifest["diagnostics"] == []
    assert manifest["risks"] == []
    assert manifest["analysis_provenance"] == {
        "mode": "deterministic",
        "fallback_reason": "provider_not_configured",
    }


def test_processor_publishes_validated_provider_enrichment() -> None:
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=FakeProvider())

    manifest = _process_manifest(processor, storage, job)

    assert manifest["classification"]["version"] == "provider-hybrid.v1"
    assert manifest["risks"][0]["severity"] == "high"
    assert manifest["clauses"][0]["source_text"] == (
        "Either party may terminate with 30 days' notice."
    )
    assert manifest["summaries"]["business"]["claims"][0]["text"] == (
        "The client account may be terminated on 30 days' notice."
    )
    assert manifest["analysis_provenance"] == {
        "mode": "hybrid",
        "provider": "openai",
        "model": "test-model",
        "schema_version": "agreement-analysis.v1",
        "prompt_version": "agreement-analysis.v1",
        "latency_ms": 30,
        "input_tokens": 10,
        "output_tokens": 20,
    }


def test_processor_records_gateway_provider_outcome_in_provenance() -> None:
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=ProvenancedProvider())

    manifest = _process_manifest(processor, storage, job)

    assert manifest["analysis_provenance"] == {
        "mode": "hybrid",
        "provider": "openai-compatible",
        "endpoint_kind": "openai-compatible",
        "model": "local-model.gguf",
        "configuration_version": "model-gateway.v1",
        "schema_version": "agreement-analysis.v1",
        "prompt_version": "agreement-analysis.v1",
        "latency_ms": 42,
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
        "cost_usd": None,
        "retry_outcome": "not_retried",
        "fallback_outcome": "hosted_fallback_succeeded",
        "safe_failure_reason": "compatible_endpoint_unavailable",
    }


def test_processor_keeps_deterministic_output_when_provider_fails() -> None:
    baseline_storage, baseline_job = _processor_input()
    baseline = _process_manifest(
        DocumentUnderstandingProcessor(baseline_storage), baseline_storage, baseline_job
    )
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=FailingProvider())

    manifest = _process_manifest(processor, storage, job)

    assert manifest["classification"] == baseline["classification"]
    assert manifest["clauses"] == baseline["clauses"]
    assert manifest["summaries"] == baseline["summaries"]
    assert manifest["risks"] == []
    assert manifest["diagnostics"][-1]["code"] == "provider_fallback"
    assert manifest["analysis_provenance"] == {
        "mode": "deterministic",
        "fallback_reason": "provider_fallback",
    }


def test_processor_rejects_invalid_provider_output_before_publishing() -> None:
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=InvalidProvider())

    manifest = _process_manifest(processor, storage, job)

    assert manifest["classification"]["version"] == "agreement-family-rules.v1"
    assert manifest["risks"] == []
    assert manifest["diagnostics"][-1] == {
        "code": "provider_fallback",
        "message": "Provider enrichment was unavailable",
        "page_numbers": [],
    }


def test_processor_propagates_provider_timeout_for_job_retry() -> None:
    storage, job = _processor_input()
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=TimeoutProvider())

    with raises(TransientProcessingError, match="Provider enrichment temporarily unavailable"):
        processor.process(job)

    assert set(storage.objects) == {job.source_storage_key}


def test_processing_runtime_injects_provider_and_post_completion_evaluation_handler(
    monkeypatch: MonkeyPatch,
) -> None:
    from agreement_intelligence_worker import main as worker_main

    configured_provider = FakeProvider()
    configured_comparator = object()
    captured: dict[str, object] = {}

    class FakeDocumentProcessor:
        def __init__(
            self,
            storage: object,
            *,
            analysis_provider: object | None = None,
        ) -> None:
            captured["analysis_provider"] = analysis_provider

        def process(self, job: ProcessingJob) -> Any:
            raise AssertionError("runtime composition must not process a job")

    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SQS_PROCESSING_QUEUE", "https://sqs.example/processing")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///worker.db")
    monkeypatch.setenv("S3_DOCUMENT_BUCKET", "documents")
    monkeypatch.setattr(worker_main, "provider_from_environment", lambda: configured_provider)
    monkeypatch.setattr(
        worker_main,
        "fallback_comparator_from_environment",
        lambda: configured_comparator,
        raising=False,
    )
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(worker_main, "processing_engine_from_url", lambda url: object())
    monkeypatch.setattr(worker_main, "SQSProcessingQueue", lambda **kwargs: object())
    monkeypatch.setattr(worker_main, "SQLAlchemyProcessingJobRepository", lambda engine: object())
    monkeypatch.setattr(worker_main, "S3ObjectStorage", lambda **kwargs: object())
    configured_sink = object()
    monkeypatch.setattr(
        worker_main,
        "SQLAlchemyPlaybookEvaluationSink",
        lambda engine, storage, **kwargs: captured.update(kwargs) or configured_sink,
    )
    configured_index_sink = object()
    monkeypatch.setattr(
        worker_main,
        "SQLAlchemyDocumentIndexSink",
        lambda engine, storage: configured_index_sink,
        raising=False,
    )
    monkeypatch.setattr(worker_main, "DocumentUnderstandingProcessor", FakeDocumentProcessor)
    monkeypatch.setattr(
        worker_main,
        "JobProcessor",
        lambda *args, **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(worker_main, "SQSProcessingMessageReceiver", lambda **kwargs: object())

    runtime = worker_main.processing_runtime_from_environment()

    assert runtime is not None
    assert captured["analysis_provider"] is configured_provider
    assert captured["fallback_model_comparator"] is configured_comparator
    assert captured["completion_handler"].handlers == (configured_sink, configured_index_sink)


def _processor_input() -> tuple[InMemoryObjectStorage, ProcessingJob]:
    source_key = "tenants/example/workspaces/example/documents/source/original.pdf"
    storage = InMemoryObjectStorage(objects={source_key: _pdf_with_text("Client Agreement")})
    return storage, ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="processing",
        attempt_count=1,
        organization_id=uuid4(),
        workspace_id=uuid4(),
        source_storage_key=source_key,
        source_checksum="a" * 64,
        source_content_type="application/pdf",
    )


def _process_manifest(
    processor: DocumentUnderstandingProcessor,
    storage: InMemoryObjectStorage,
    job: ProcessingJob,
) -> dict[str, Any]:
    artifact = processor.process(job)
    return cast(dict[str, Any], json.loads(storage.objects[artifact.key]))


def _valid_provider_response(anchor_id: str) -> ProviderAnalysis:
    return ProviderAnalysis(
        classification={
            "family": "client_agreement",
            "confidence": 0.91,
            "rationale": "The agreement governs a client account.",
            "citation_anchor_ids": [anchor_id],
        },
        clauses=[
            {
                "category": "termination",
                "normalized_fields": [{"name": "notice", "value": "30 days"}],
                "source_excerpt": "Either party may terminate with 30 days' notice.",
                "confidence": 0.88,
                "citation_anchor_ids": [anchor_id],
            }
        ],
        risks=[
            {
                "severity": "high",
                "explanation": "Termination is available without cause.",
                "affected_category": "termination",
                "confidence": 0.82,
                "citation_anchor_ids": [anchor_id],
            }
        ],
        summaries={
            "business": {
                "claim": "The client account may be terminated on 30 days' notice.",
                "citation_anchor_ids": [anchor_id],
            },
            "legal": {
                "claim": "The termination clause applies to either party.",
                "citation_anchor_ids": [anchor_id],
            },
        },
        model="test-model",
        input_tokens=10,
        output_tokens=20,
        latency_ms=30,
    )


def _pdf_with_text(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()
