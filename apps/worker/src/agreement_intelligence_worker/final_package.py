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
    def __init__(
        self, *, client: Any, bucket: str, production: bool = False, kms_key_id: str | None = None
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._production = production
        self._kms_key_id = kms_key_id

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        try:
            request: dict[str, object] = dict(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ChecksumSHA256=b64encode(bytes.fromhex(sha256)).decode("ascii"),
                IfNoneMatch="*",
            )
            if self._production:
                request["ServerSideEncryption"] = "aws:kms"
                if self._kms_key_id:
                    request["SSEKMSKeyId"] = self._kms_key_id
            self._client.put_object(**request)
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


@dataclass(frozen=True)
class PreparedFinalPackage:
    event_id: UUID
    workflow_id: UUID
    correlation_id: str
    snapshot: dict[str, object]
    manifest_key: str
    pdf_key: str
    manifest_content: bytes
    pdf_content: bytes
    manifest_checksum: str
    pdf_checksum: str


class TerminalReviewPackageGenerator:
    """Prepare frozen payloads before locks, then commit them inside the caller's fence."""

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
        prepared = self.prepare(
            connection,
            event_id=event_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
        )
        return self.commit(connection, prepared=prepared)

    def prepare(
        self,
        connection: Connection,
        *,
        event_id: UUID,
        workflow_id: UUID,
        correlation_id: str,
    ) -> PreparedFinalPackage:
        event = (
            connection.execute(
                text(
                    """
                    SELECT workflow_id, organization_id, workspace_id, event_type,
                           correlation_id, package_snapshot,
                           package_manifest_key, package_pdf_key
                    FROM review_workflow_outbox
                    WHERE id = :event_id
                    """
                ),
                {"event_id": _database_uuid(connection, event_id)},
            )
            .mappings()
            .one_or_none()
        )
        if (
            event is None
            or event["event_type"] != "review.workflow.terminal"
            or str(event["workflow_id"]) != str(workflow_id)
            or event["correlation_id"] != correlation_id
        ):
            raise FinalPackageConflictError("terminal workflow event identity conflict")
        frozen = event["package_snapshot"]
        if frozen is None:
            raise FinalPackageConflictError("terminal package snapshot is missing")
        snapshot = loads(frozen) if isinstance(frozen, str) else dict(frozen)
        provenance = snapshot.get("provenance")
        if not isinstance(provenance, dict) or (
            provenance.get("workflow_event_id") != str(event_id)
            or provenance.get("workflow_correlation_id") != correlation_id
            or snapshot.get("workflow_id") != str(workflow_id)
            or snapshot.get("organization_id") != str(event["organization_id"])
            or snapshot.get("workspace_id") != str(event["workspace_id"])
            or snapshot.get("state") not in _TERMINAL_STATES
        ):
            raise FinalPackageConflictError("terminal package snapshot identity conflict")

        manifest_content = dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        manifest_checksum = sha256(manifest_content).hexdigest()
        pdf_content = _deterministic_pdf(
            [
                "Agreement Intelligence - Final Review Package",
                f"Agreement ID: {snapshot['agreement_id']}",
                f"Review ID: {snapshot['review_id']}",
                f"Outcome: {snapshot['state']}",
                f"Manifest checksum: sha256:{manifest_checksum}",
            ]
        )
        pdf_checksum = sha256(pdf_content).hexdigest()
        base = (
            f"reviews/{snapshot['organization_id']}/{snapshot['workspace_id']}/"
            f"{snapshot['review_id']}/final-package"
        )
        manifest_key = f"{base}/manifest.json"
        pdf_key = f"{base}/report.pdf"
        if (
            snapshot.get("manifest_key") != manifest_key
            or snapshot.get("pdf_key") != pdf_key
            or event["package_manifest_key"] != manifest_key
            or event["package_pdf_key"] != pdf_key
        ):
            raise FinalPackageConflictError("terminal package object key conflict")
        return PreparedFinalPackage(
            event_id=event_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            snapshot=snapshot,
            manifest_key=manifest_key,
            pdf_key=pdf_key,
            manifest_content=manifest_content,
            pdf_content=pdf_content,
            manifest_checksum=manifest_checksum,
            pdf_checksum=pdf_checksum,
        )

    def commit(
        self, connection: Connection, *, prepared: PreparedFinalPackage
    ) -> PackageGenerationResult:
        snapshot = prepared.snapshot
        existing = (
            connection.execute(
                text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                {"review_id": snapshot["review_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            expected = {
                "workflow_id": str(prepared.workflow_id),
                "state": snapshot["state"],
                "manifest_key": prepared.manifest_key,
                "pdf_key": prepared.pdf_key,
                "manifest_checksum": prepared.manifest_checksum,
                "pdf_checksum": prepared.pdf_checksum,
            }
            if any(str(existing[key]) != str(value) for key, value in expected.items()):
                raise FinalPackageConflictError("final package metadata conflict")
            self._ensure_object(
                key=prepared.manifest_key,
                content=prepared.manifest_content,
                content_type="application/json",
            )
            self._ensure_object(
                key=prepared.pdf_key,
                content=prepared.pdf_content,
                content_type="application/pdf",
            )
            return PackageGenerationResult(package_id=UUID(str(existing["id"])), created=False)

        self._ensure_object(
            key=prepared.manifest_key,
            content=prepared.manifest_content,
            content_type="application/json",
        )
        self._ensure_object(
            key=prepared.pdf_key,
            content=prepared.pdf_content,
            content_type="application/pdf",
        )
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
                "organization_id": snapshot["organization_id"],
                "workspace_id": snapshot["workspace_id"],
                "review_id": snapshot["review_id"],
                "workflow_id": snapshot["workflow_id"],
                "state": snapshot["state"],
                "manifest_key": prepared.manifest_key,
                "pdf_key": prepared.pdf_key,
                "manifest_checksum": prepared.manifest_checksum,
                "pdf_checksum": prepared.pdf_checksum,
            },
        )
        self._record_audit(
            connection,
            package_id=package_id,
            workflow=snapshot,
            event_id=prepared.event_id,
            correlation_id=prepared.correlation_id,
            manifest_checksum=prepared.manifest_checksum,
            pdf_checksum=prepared.pdf_checksum,
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
            "CAST(:{name} AS JSONB)" if connection.dialect.name == "postgresql" else ":{name}"
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
