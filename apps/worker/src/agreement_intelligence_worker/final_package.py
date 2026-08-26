"""Durably create immutable terminal-review package objects and metadata."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from hashlib import sha256
from json import dumps, loads
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.engine import Connection

FINAL_PACKAGE_WORKER_ACTOR_ID = uuid5(
    NAMESPACE_URL, "https://agreement-intelligence.local/actors/review-final-package-worker"
)
_TERMINAL_STATES = frozenset({"approved", "rejected", "revision_requested"})


class FinalPackageConflictError(RuntimeError):
    """An immutable object or metadata row differs from the terminal workflow snapshot."""


class FinalPackageNotTerminalError(RuntimeError):
    """A non-terminal workflow was delivered as package-generation work."""


@dataclass(frozen=True)
class StoredPackageObject:
    content: bytes
    content_type: str


class FinalPackageStorage(Protocol):
    def put_immutable(
        self, key: str, content: bytes, *, content_type: str, sha256: str
    ) -> bool: ...

    def read(self, key: str) -> StoredPackageObject | None: ...


class S3FinalPackageStorage:
    def __init__(self, *, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put_immutable(
        self, key: str, content: bytes, *, content_type: str, sha256: str
    ) -> bool:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ChecksumSHA256=b64encode(bytes.fromhex(sha256)).decode("ascii"),
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

    def read(self, key: str) -> StoredPackageObject | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code", "")) in {
                "NoSuchKey",
                "NotFound",
                "404",
            }:
                return None
            raise
        return StoredPackageObject(
            content=cast(bytes, response["Body"].read()),
            content_type=str(response.get("ContentType", "application/octet-stream")),
        )


@dataclass(frozen=True)
class PackageGenerationResult:
    package_id: UUID
    created: bool


class TerminalReviewPackageGenerator:
    """Create one recoverable package from a locked terminal workflow outbox event."""

    def __init__(self, storage: FinalPackageStorage) -> None:
        self._storage = storage

    def generate(
        self,
        connection: Connection,
        *,
        event_id: UUID,
        workflow_id: UUID,
        correlation_id: str,
    ) -> PackageGenerationResult:
        workflow = connection.execute(
            text(
                """
                SELECT
                    workflow.id AS workflow_id,
                    workflow.organization_id,
                    workflow.workspace_id,
                    workflow.review_id,
                    workflow.policy_version_id,
                    workflow.state,
                    workflow.revision,
                    review.agreement_id,
                    review.agreement_version_id
                FROM review_workflows AS workflow
                JOIN review_cases AS review ON review.id = workflow.review_id
                WHERE workflow.id = :workflow_id
                """
                + (" FOR UPDATE OF workflow" if connection.dialect.name == "postgresql" else "")
            ),
            {"workflow_id": _database_uuid(connection, workflow_id)},
        ).mappings().one_or_none()
        if workflow is None or workflow["state"] not in _TERMINAL_STATES:
            raise FinalPackageNotTerminalError(str(workflow_id))

        manifest_content = self._manifest(
            connection,
            workflow=workflow,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        manifest_checksum = sha256(manifest_content).hexdigest()
        pdf_content = _deterministic_pdf(
            [
                "Agreement Intelligence - Final Review Package",
                f"Agreement ID: {workflow['agreement_id']}",
                f"Review ID: {workflow['review_id']}",
                f"Outcome: {workflow['state']}",
                f"Manifest checksum: sha256:{manifest_checksum}",
            ]
        )
        pdf_checksum = sha256(pdf_content).hexdigest()
        base = (
            f"reviews/{workflow['organization_id']}/{workflow['workspace_id']}/"
            f"{workflow['review_id']}/final-package"
        )
        manifest_key = f"{base}/manifest.json"
        pdf_key = f"{base}/report.pdf"
        existing = connection.execute(
            text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
            {"review_id": workflow["review_id"]},
        ).mappings().one_or_none()
        if existing is not None:
            expected = {
                "workflow_id": str(workflow_id),
                "state": workflow["state"],
                "manifest_key": manifest_key,
                "pdf_key": pdf_key,
                "manifest_checksum": manifest_checksum,
                "pdf_checksum": pdf_checksum,
            }
            if any(str(existing[key]) != str(value) for key, value in expected.items()):
                raise FinalPackageConflictError("final package metadata conflict")
            self._ensure_object(
                key=manifest_key,
                content=manifest_content,
                content_type="application/json",
            )
            self._ensure_object(key=pdf_key, content=pdf_content, content_type="application/pdf")
            return PackageGenerationResult(package_id=UUID(str(existing["id"])), created=False)

        self._ensure_object(
            key=manifest_key,
            content=manifest_content,
            content_type="application/json",
        )
        self._ensure_object(key=pdf_key, content=pdf_content, content_type="application/pdf")
        package_id = uuid4()
        connection.execute(
            text(
                """
                INSERT INTO review_final_packages (
                    id, organization_id, workspace_id, review_id, workflow_id, state,
                    manifest_key, pdf_key, manifest_checksum, pdf_checksum
                ) VALUES (
                    :id, :organization_id, :workspace_id, :review_id, :workflow_id, :state,
                    :manifest_key, :pdf_key, :manifest_checksum, :pdf_checksum
                )
                """
            ),
            {
                "id": _database_uuid(connection, package_id),
                "organization_id": workflow["organization_id"],
                "workspace_id": workflow["workspace_id"],
                "review_id": workflow["review_id"],
                "workflow_id": workflow["workflow_id"],
                "state": workflow["state"],
                "manifest_key": manifest_key,
                "pdf_key": pdf_key,
                "manifest_checksum": manifest_checksum,
                "pdf_checksum": pdf_checksum,
            },
        )
        self._record_audit(
            connection,
            package_id=package_id,
            workflow=workflow,
            event_id=event_id,
            correlation_id=correlation_id,
            manifest_checksum=manifest_checksum,
            pdf_checksum=pdf_checksum,
        )
        return PackageGenerationResult(package_id=package_id, created=True)

    def _ensure_object(self, *, key: str, content: bytes, content_type: str) -> None:
        checksum = sha256(content).hexdigest()
        stored = self._storage.read(key)
        if stored is None:
            if self._storage.put_immutable(
                key,
                content,
                content_type=content_type,
                sha256=checksum,
            ):
                return
            stored = self._storage.read(key)
        if (
            stored is None
            or stored.content_type != content_type
            or sha256(stored.content).hexdigest() != checksum
        ):
            raise FinalPackageConflictError(f"immutable object conflict: {key}")

    def _manifest(
        self,
        connection: Connection,
        *,
        workflow: Any,
        event_id: UUID,
        correlation_id: str,
    ) -> bytes:
        workflow_id = workflow["workflow_id"]
        review_id = workflow["review_id"]
        decisions = connection.execute(
            text(
                """
                SELECT actor_id, action, workflow_stage_id, occurred_at
                FROM review_workflow_decisions
                WHERE workflow_id = :workflow_id
                ORDER BY occurred_at, id
                """
            ),
            {"workflow_id": workflow_id},
        ).mappings()
        stages = connection.execute(
            text(
                """
                SELECT id, ordinal, state, activated_at, completed_at
                FROM review_workflow_stages
                WHERE workflow_id = :workflow_id
                ORDER BY ordinal
                """
            ),
            {"workflow_id": workflow_id},
        ).mappings()
        assignments = connection.execute(
            text(
                """
                SELECT id, assignee_id, status, due_at
                FROM review_assignments
                WHERE review_id = :review_id
                ORDER BY created_at, id
                """
            ),
            {"review_id": review_id},
        ).mappings()
        comments = connection.execute(
            text(
                """
                SELECT id, author_id, finding_id, created_at
                FROM review_comments
                WHERE review_id = :review_id
                ORDER BY created_at, id
                """
            ),
            {"review_id": review_id},
        ).mappings()
        audit_refs = connection.execute(
            text(
                """
                SELECT id FROM audit_events
                WHERE organization_id = :organization_id
                  AND workspace_id = :workspace_id
                  AND resource_id = :review_id
                ORDER BY occurred_at, id
                """
            ),
            {
                "organization_id": workflow["organization_id"],
                "workspace_id": workflow["workspace_id"],
                "review_id": review_id,
            },
        ).scalars()
        findings = connection.execute(
            text(
                """
                SELECT finding.id, finding.result, finding.severity, finding.citation_ids
                FROM playbook_findings AS finding
                JOIN playbook_evaluations AS evaluation ON evaluation.id = finding.evaluation_id
                WHERE finding.organization_id = :organization_id
                  AND finding.workspace_id = :workspace_id
                  AND evaluation.agreement_id = :agreement_id
                ORDER BY finding.id
                """
            ),
            {
                "organization_id": workflow["organization_id"],
                "workspace_id": workflow["workspace_id"],
                "agreement_id": workflow["agreement_id"],
            },
        ).mappings()
        manifest = {
            "review_id": str(review_id),
            "agreement_id": str(workflow["agreement_id"]),
            "agreement_version_id": (
                str(workflow["agreement_version_id"])
                if workflow["agreement_version_id"] is not None
                else None
            ),
            "workflow_id": str(workflow_id),
            "policy_version_id": str(workflow["policy_version_id"]),
            "state": workflow["state"],
            "revision": workflow["revision"],
            "decisions": [
                {
                    "actor_id": str(item["actor_id"]),
                    "action": item["action"],
                    "stage_id": str(item["workflow_stage_id"]),
                    "occurred_at": _timestamp(item["occurred_at"]),
                }
                for item in decisions
            ],
            "stages": [
                {
                    "id": str(item["id"]),
                    "ordinal": item["ordinal"],
                    "state": item["state"],
                    "activated_at": _timestamp(item["activated_at"]),
                    "completed_at": _timestamp(item["completed_at"]),
                }
                for item in stages
            ],
            "assignments": [
                {
                    "id": str(item["id"]),
                    "assignee_id": str(item["assignee_id"]),
                    "status": item["status"],
                    "due_at": _timestamp(item["due_at"]),
                }
                for item in assignments
            ],
            "comments": [
                {
                    "id": str(item["id"]),
                    "author_id": str(item["author_id"]),
                    "finding_id": str(item["finding_id"]) if item["finding_id"] else None,
                    "created_at": _timestamp(item["created_at"]),
                }
                for item in comments
            ],
            "findings": [
                {
                    "id": str(item["id"]),
                    "result": item["result"],
                    "severity": item["severity"],
                    "citation_ids": _json_value(item["citation_ids"]),
                }
                for item in findings
            ],
            "audit_event_ids": [str(item) for item in audit_refs],
            "provenance": {
                "generator": "review-final-package-worker",
                "source": "postgresql",
                "workflow_correlation_id": correlation_id,
                "workflow_event_id": str(event_id),
                "workflow_revision": workflow["revision"],
            },
        }
        return dumps(manifest, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _record_audit(
        connection: Connection,
        *,
        package_id: UUID,
        workflow: Any,
        event_id: UUID,
        correlation_id: str,
        manifest_checksum: str,
        pdf_checksum: str,
    ) -> None:
        json_cast = (
            "CAST(:{name} AS JSONB)"
            if connection.dialect.name == "postgresql"
            else ":{name}"
        )
        statement = """
            INSERT INTO audit_events (
                id, organization_id, workspace_id, actor_id, action, resource_type,
                resource_id, outcome, correlation_id, before_ref, after_ref, metadata_json
            ) VALUES (
                :id, :organization_id, :workspace_id, :actor_id,
                'review_final_package_generated', 'review_final_package', :resource_id,
                'accepted', :correlation_id, {before_ref}, {after_ref}, {metadata_json}
            )
        """.format(
            before_ref=json_cast.format(name="before_ref"),
            after_ref=json_cast.format(name="after_ref"),
            metadata_json=json_cast.format(name="metadata_json"),
        )
        connection.execute(
            text(statement),
            {
                "id": _database_uuid(connection, uuid4()),
                "organization_id": workflow["organization_id"],
                "workspace_id": workflow["workspace_id"],
                "actor_id": _database_uuid(connection, FINAL_PACKAGE_WORKER_ACTOR_ID),
                "resource_id": _database_uuid(connection, package_id),
                "correlation_id": correlation_id,
                "before_ref": dumps({"state": "not_generated"}, sort_keys=True),
                "after_ref": dumps(
                    {
                        "manifest_checksum": manifest_checksum,
                        "pdf_checksum": pdf_checksum,
                        "state": workflow["state"],
                    },
                    sort_keys=True,
                ),
                "metadata_json": dumps(
                    {
                        "actor_type": "system",
                        "event_id": str(event_id),
                        "review_id": str(workflow["review_id"]),
                        "workflow_id": str(workflow["workflow_id"]),
                        "worker": "review-final-package",
                    },
                    sort_keys=True,
                ),
            },
        )


def _database_uuid(connection: Connection, value: UUID) -> UUID | str:
    return value if connection.dialect.name == "postgresql" else str(value)


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return loads(value)
    except ValueError:
        return value


def _deterministic_pdf(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 10 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -14 Td")
        commands.append(f"({_pdf_literal(line)}) Tj")
    commands.append("ET")
    stream = ("\n".join(commands) + "\n").encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream"
        ),
    ]
    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, item in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii"))
        content.extend(item)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(content)


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
