from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Protocol, cast

from botocore.exceptions import ClientError

from agreement_intelligence_worker.classification import classify_document
from agreement_intelligence_worker.clause_extraction import extract_clauses
from agreement_intelligence_worker.document_understanding import ParsedDocument, parse_document
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    PermanentProcessingError,
    ProcessingJob,
)

_SCHEMA_VERSION = "document-analysis.v1"
_PIPELINE_VERSION = "sprint-2.v1"


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
    def __init__(self, storage: ObjectStorage) -> None:
        self._storage = storage

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
        manifest = _manifest(parsed, source)
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


def _manifest(parsed: ParsedDocument, source: _SourceDocument) -> dict[str, object]:
    classification = classify_document(
        "\n".join(block.text for page in parsed.pages for block in page.blocks)
    )
    clauses = extract_clauses(
        [(block.anchor_id, block.text) for page in parsed.pages for block in page.blocks]
    )
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
        "clauses": clauses,
        "summaries": {},
    }
