from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Protocol, cast

from botocore.exceptions import ClientError

from agreement_intelligence_worker.analysis_provider import AnalysisProvider, ProviderTransientError
from agreement_intelligence_worker.analysis_validation import (
    ProviderOutputValidationError,
    ValidatedAnalysis,
    validate_provider_analysis,
)
from agreement_intelligence_worker.classification import classify_document
from agreement_intelligence_worker.clause_extraction import extract_clauses
from agreement_intelligence_worker.document_understanding import ParsedDocument, parse_document
from agreement_intelligence_worker.guardrails import (
    GuardrailDecision,
    record_guardrail_span_provenance,
    validate_untrusted_evidence,
)
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    PermanentProcessingError,
    ProcessingJob,
    TransientProcessingError,
)
from agreement_intelligence_worker.summaries import generate_summaries

_SCHEMA_VERSION = "document-analysis.v1"
_PIPELINE_VERSION = "sprint-2.v1"
_PROVIDER_ANALYSIS_VERSION = "provider-hybrid.v1"
_PROVIDER_SCHEMA_VERSION = "agreement-analysis.v1"
_PROVIDER_PROMPT_VERSION = "agreement-analysis.v1"
_MAX_PROVIDER_BLOCKS = 100
_MAX_PROVIDER_BLOCK_CHARACTERS = 4_000


class ObjectStorage(Protocol):
    def read(self, key: str) -> bytes | None: ...

    def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool: ...


class S3ObjectStorage:
    def __init__(self, *, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def read(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) in {"NoSuchKey", "404"}:
                return None
            raise
        return cast(bytes, response["Body"].read())

    def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
                "409",
                "412",
            }:
                return False
            raise
        return True


class DocumentUnderstandingProcessor:
    def __init__(
        self,
        storage: ObjectStorage,
        *,
        analysis_provider: AnalysisProvider | None = None,
    ) -> None:
        self._storage = storage
        self._analysis_provider = analysis_provider

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        source = _source_from(job)
        content = self._storage.read(source.storage_key)
        if content is None:
            raise PermanentProcessingError("The selected source document is unavailable")
        try:
            parsed = parse_document(
                content=content,
                content_type=source.content_type,
                source_checksum=source.checksum,
            )
        except ValueError as error:
            raise PermanentProcessingError("The source document cannot be parsed") from error
        artifact_key = _artifact_key(job, source.checksum)
        manifest = _manifest(parsed, source, self._analysis_provider)
        self._storage.put_immutable(
            artifact_key,
            json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode(),
            content_type="application/json",
        )
        return CompletedArtifact(job_id=job.id, key=artifact_key)


class _SourceDocument:
    def __init__(self, storage_key: str, checksum: str, content_type: str) -> None:
        self.storage_key = storage_key
        self.checksum = checksum
        self.content_type = content_type


def _source_from(job: ProcessingJob) -> _SourceDocument:
    if not job.source_storage_key or not job.source_checksum or not job.source_content_type:
        raise PermanentProcessingError("The processing job has no source document")
    if job.organization_id is None or job.workspace_id is None:
        raise PermanentProcessingError("The processing job has no workspace scope")
    return _SourceDocument(
        storage_key=job.source_storage_key,
        checksum=job.source_checksum,
        content_type=job.source_content_type,
    )


def _artifact_key(job: ProcessingJob, checksum: str) -> str:
    assert job.organization_id is not None
    assert job.workspace_id is not None
    return (
        f"tenants/{job.organization_id}/workspaces/{job.workspace_id}/agreements/{job.agreement_id}/"
        f"analysis/{checksum}/{_SCHEMA_VERSION}.json"
    )


def _manifest(
    parsed: ParsedDocument,
    source: _SourceDocument,
    analysis_provider: AnalysisProvider | None,
) -> dict[str, object]:
    blocks = [(block.anchor_id, block.text) for page in parsed.pages for block in page.blocks]
    provider_blocks = [
        (anchor_id, text[:_MAX_PROVIDER_BLOCK_CHARACTERS])
        for anchor_id, text in blocks[:_MAX_PROVIDER_BLOCKS]
    ]
    guardrail_decision = validate_untrusted_evidence(blocks, {anchor_id for anchor_id, _ in blocks})
    record_guardrail_span_provenance(guardrail_decision)
    manifest = _deterministic_manifest(parsed, source, blocks)
    if analysis_provider is None:
        manifest["analysis_provenance"] = _deterministic_provenance(
            "provider_not_configured", guardrail_decision
        )
        return manifest
    if guardrail_decision.status != "allow":
        return _provider_fallback(manifest, guardrail_decision)

    try:
        provider_analysis = analysis_provider.analyze(provider_blocks)
    except (ProviderTransientError, TimeoutError, ConnectionError) as error:
        raise TransientProcessingError("Provider enrichment temporarily unavailable") from error
    except Exception:
        return _provider_fallback(manifest, guardrail_decision)

    try:
        enriched = validate_provider_analysis(
            provider_analysis,
            dict(provider_blocks),
        )
    except ProviderOutputValidationError:
        return _provider_fallback(manifest, guardrail_decision)

    _merge_provider_enrichment(manifest, enriched)
    manifest["analysis_provenance"] = _provider_provenance(enriched, guardrail_decision)
    return manifest


def _deterministic_manifest(
    parsed: ParsedDocument,
    source: _SourceDocument,
    blocks: list[tuple[str, str]],
) -> dict[str, object]:
    classification = classify_document("\n".join(text for _, text in blocks))
    return {
        "schema_version": _SCHEMA_VERSION,
        "pipeline_version": _PIPELINE_VERSION,
        "source": {
            "checksum": source.checksum,
            "storage_key": source.storage_key,
            "content_type": source.content_type,
        },
        "document": {"pages": [asdict(page) for page in parsed.pages]},
        "diagnostics": [asdict(diagnostic) for diagnostic in parsed.diagnostics],
        "citations": [asdict(citation) for citation in parsed.citations],
        "classification": asdict(classification),
        "clauses": extract_clauses(blocks),
        "risks": [],
        "summaries": generate_summaries(blocks),
    }


def _provider_fallback(
    manifest: dict[str, object], guardrail_decision: GuardrailDecision
) -> dict[str, object]:
    diagnostics = cast(list[dict[str, object]], manifest["diagnostics"])
    diagnostics.append(
        {
            "code": "provider_fallback",
            "message": "Provider enrichment was unavailable",
            "page_numbers": [],
        }
    )
    manifest["analysis_provenance"] = _deterministic_provenance(
        "provider_fallback", guardrail_decision
    )
    return manifest


def _provider_artifact_fields(enriched: ValidatedAnalysis) -> dict[str, object]:
    clauses = [
        {
            "category": clause["category"],
            "normalized_fields": clause["normalized_fields"],
            "source_text": clause["source_excerpt"],
            "confidence": clause["confidence"],
            "citation_anchor_ids": clause["citation_anchor_ids"],
            "extraction_version": _PROVIDER_ANALYSIS_VERSION,
        }
        for clause in enriched.clauses
    ]
    summaries = {
        summary_type: {
            "version": _PROVIDER_ANALYSIS_VERSION,
            "claims": [
                {
                    "text": summary["claim"],
                    "citation_anchor_ids": summary["citation_anchor_ids"],
                }
            ],
        }
        for summary_type, summary in enriched.summaries.items()
    }
    return {
        "clauses": clauses,
        "risks": enriched.risks,
        "summaries": summaries,
    }


def _merge_provider_enrichment(manifest: dict[str, object], enriched: ValidatedAnalysis) -> None:
    provider_fields = _provider_artifact_fields(enriched)
    manifest["clauses"] = _merge_cited_items(
        cast(list[dict[str, object]], manifest["clauses"]),
        cast(list[dict[str, object]], provider_fields["clauses"]),
        identity_field="category",
    )
    manifest["risks"] = _merge_cited_items(
        cast(list[dict[str, object]], manifest["risks"]),
        cast(list[dict[str, object]], provider_fields["risks"]),
        identity_field="affected_category",
    )
    manifest["summaries"] = _merge_summary_claims(
        cast(dict[str, object], manifest["summaries"]),
        cast(dict[str, object], provider_fields["summaries"]),
    )


def _merge_summary_claims(
    deterministic: dict[str, object], enrichment: dict[str, object]
) -> dict[str, object]:
    for summary_type, summary_value in deterministic.items():
        summary = cast(dict[str, object], summary_value)
        provider_summary = cast(dict[str, object], enrichment[summary_type])
        summary["claims"] = _merge_cited_items(
            cast(list[dict[str, object]], summary["claims"]),
            cast(list[dict[str, object]], provider_summary["claims"]),
            identity_field=None,
        )
    return deterministic


def _merge_cited_items(
    deterministic: list[dict[str, object]],
    enrichment: list[dict[str, object]],
    *,
    identity_field: str | None,
) -> list[dict[str, object]]:
    merged = list(deterministic)
    identities = {_cited_identity(item, identity_field) for item in deterministic}
    for item in enrichment:
        identity = _cited_identity(item, identity_field)
        if identity in identities:
            continue
        merged.append(item)
        identities.add(identity)
    return merged


def _cited_identity(
    item: dict[str, object], identity_field: str | None
) -> tuple[object, tuple[str, ...]]:
    identity = item.get(identity_field) if identity_field is not None else None
    citations = item.get("citation_anchor_ids")
    citation_ids = (
        tuple(sorted({citation for citation in citations if isinstance(citation, str)}))
        if isinstance(citations, list)
        else ()
    )
    return identity, citation_ids


def _deterministic_provenance(
    fallback_reason: str, guardrail_decision: GuardrailDecision
) -> dict[str, object]:
    return {
        "mode": "deterministic",
        "fallback_reason": fallback_reason,
        "guardrail": guardrail_decision.provenance(),
    }


def _provider_provenance(
    enriched: ValidatedAnalysis, guardrail_decision: GuardrailDecision
) -> dict[str, object]:
    provenance: dict[str, object] = {
        "mode": "hybrid",
        "provider": "openai",
        "model": enriched.provenance["model"],
        "schema_version": _PROVIDER_SCHEMA_VERSION,
        "prompt_version": _PROVIDER_PROMPT_VERSION,
        "latency_ms": enriched.provenance["latency_ms"],
        "guardrail": guardrail_decision.provenance(),
    }
    if enriched.provenance["input_tokens"] is not None:
        provenance["input_tokens"] = enriched.provenance["input_tokens"]
    if enriched.provenance["output_tokens"] is not None:
        provenance["output_tokens"] = enriched.provenance["output_tokens"]
    for key in (
        "endpoint_kind",
        "configuration_version",
        "total_tokens",
        "cost_usd",
        "retry_outcome",
        "fallback_outcome",
        "safe_failure_reason",
    ):
        if key in enriched.provenance:
            provenance[key] = enriched.provenance[key]
    if "provider" in enriched.provenance:
        provenance["provider"] = enriched.provenance["provider"]
    return provenance
