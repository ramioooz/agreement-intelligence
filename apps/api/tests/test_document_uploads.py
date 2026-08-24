from collections.abc import Generator, Mapping, MutableMapping
from io import BytesIO
from typing import Any, cast
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from agreement_intelligence_api.documents.storage import S3DocumentStorage, StoredDocument
from agreement_intelligence_api.documents.validation import (
    DocumentValidationError,
    validate_document,
)
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.routes import get_identity_service
from agreement_intelligence_api.main import app
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from pytest import MonkeyPatch, fixture, raises


class InMemoryDocumentStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}

    def put_immutable(
        self,
        key: str,
        content: bytes,
        *,
        content_type: str,
        sha256: str,
    ) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = (content, content_type, sha256)
        return True

    def read(self, key: str) -> StoredDocument | None:
        stored = self.objects.get(key)
        if stored is None:
            return None
        return StoredDocument(content=stored[0], content_type=stored[1])


TENANT_ID = "123e4567-e89b-42d3-a456-426614174000"
WORKSPACE_ID = "456e4567-e89b-42d3-a456-426614174000"
OTHER_WORKSPACE_ID = "456e4567-e89b-42d3-a456-426614174001"


class FakeIdentityService:
    def __init__(self, *, allowed_workspaces: set[UUID]) -> None:
        self.allowed_workspaces = allowed_workspaces

    def can_access_workspace(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        permission: PermissionKey,
    ) -> bool:
        return (
            principal.user_id == UUID("00000000-0000-0000-0000-000000000001")
            and organization_id == UUID(TENANT_ID)
            and workspace_id in self.allowed_workspaces
            and permission in {PermissionKey.AGREEMENTS_CREATE, PermissionKey.AGREEMENTS_READ}
        )


@fixture(autouse=True)
def document_test_app(monkeypatch: MonkeyPatch) -> Generator[None]:
    monkeypatch.delenv("MAX_DOCUMENT_UPLOAD_BYTES", raising=False)
    app.dependency_overrides.clear()
    app.state.document_storage = InMemoryDocumentStorage()
    app.dependency_overrides[current_principal] = lambda: Principal(
        user_id=UUID("00000000-0000-0000-0000-000000000001")
    )
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentityService(
        allowed_workspaces={UUID(WORKSPACE_ID)}
    )
    yield
    app.dependency_overrides.clear()
    if hasattr(app.state, "document_storage"):
        del app.state.document_storage


def upload_form(
    *,
    organization_id: str = TENANT_ID,
    workspace_id: str = WORKSPACE_ID,
) -> dict[str, str]:
    return {"organization_id": organization_id, "workspace_id": workspace_id}


def _docx(*, extra_entries: dict[str, bytes] | None = None) -> bytes:
    document = BytesIO()
    entries = {
        "[Content_Types].xml": b"<Types />",
        "_rels/.rels": b"<Relationships />",
        "word/document.xml": b"<w:document />",
    }
    if extra_entries is not None:
        entries.update(extra_entries)
    with ZipFile(document, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return document.getvalue()


def test_uploading_a_valid_pdf_stores_an_immutable_scoped_original() -> None:
    storage = InMemoryDocumentStorage()
    app.state.document_storage = storage

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={"file": ("signed-agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json() == {
        "document_id": "678f1157-87ab-563b-bba3-cb44f564c7ed",
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "original_filename": "signed-agreement.pdf",
        "content_type": "application/pdf",
        "byte_size": 17,
        "sha256": "4f040ded5c8f774d24db6aaff5229c3bd95631d8b097374dcb12c6501fbc8511",
        "object_key": (
            "tenants/123e4567-e89b-42d3-a456-426614174000/"
            "workspaces/456e4567-e89b-42d3-a456-426614174000/"
            "documents/4f040ded5c8f774d24db6aaff5229c3bd95631d8b097374dcb12c6501fbc8511/"
            "original.pdf"
        ),
        "duplicate": False,
    }
    assert len(storage.objects) == 1


def test_duplicate_upload_returns_the_same_scoped_document_reference() -> None:
    storage = InMemoryDocumentStorage()
    app.state.document_storage = storage
    client = TestClient(app)
    upload = {"file": ("signed-agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")}

    first = client.post("/documents", data=upload_form(), files=upload)
    duplicate = client.post("/documents", data=upload_form(), files=upload)

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["document_id"] == first.json()["document_id"]
    assert duplicate.json()["object_key"] == first.json()["object_key"]
    assert len(storage.objects) == 1


def test_upload_rejects_file_with_mismatched_pdf_signature() -> None:
    app.state.document_storage = InMemoryDocumentStorage()

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={"file": ("agreement.pdf", b"not a PDF", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The file content is not a valid PDF signature."


def test_upload_rejects_a_declared_mime_type_that_does_not_match_the_extension() -> None:
    app.state.document_storage = InMemoryDocumentStorage()

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={
            "file": (
                "agreement.pdf",
                b"%PDF-1.7\ncontract",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The declared MIME type does not match the file extension."


def test_upload_accepts_a_docx_with_required_zip_entries() -> None:
    app.state.document_storage = InMemoryDocumentStorage()

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={
            "file": (
                "agreement.docx",
                _docx(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["content_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.json()["object_key"].endswith("/original.docx")


def test_upload_rejects_a_compressed_docx_with_an_excessive_expansion_ratio() -> None:
    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={
            "file": (
                "agreement.docx",
                _docx(extra_entries={"word/media/bomb.bin": b"x" * 1_100_000}),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "The DOCX archive exceeds document safety limits."


def test_upload_rejects_docx_archives_with_unsafe_paths_or_missing_required_parts() -> None:
    unsafe_path = _docx(extra_entries={"../outside.xml": b"x"})
    missing_root_relationship = BytesIO()
    with ZipFile(missing_root_relationship, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<w:document />")

    for content in (unsafe_path, missing_root_relationship.getvalue()):
        with raises(DocumentValidationError, match="DOCX archive"):
            validate_document(
                filename="agreement.docx",
                content=content,
                declared_content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                max_bytes=2_000_000,
            )


def test_upload_rejects_docx_archives_with_too_many_entries() -> None:
    content = _docx(
        extra_entries={f"custom/{index}.xml": b"x" for index in range(126)},
    )

    with raises(DocumentValidationError, match="exceeds document safety limits"):
        validate_document(
            filename="agreement.docx",
            content=content,
            declared_content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            max_bytes=2_000_000,
        )


def test_upload_enforces_the_configured_file_size_limit(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_UPLOAD_BYTES", "16")
    app.state.document_storage = InMemoryDocumentStorage()

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        files={"file": ("agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "The request body exceeds the maximum allowed size."


def test_upload_rejects_missing_content_length_before_route_logic(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_UPLOAD_BYTES", "16")
    app.state.document_storage = InMemoryDocumentStorage()
    status: int | None = None

    async def receive() -> MutableMapping[str, Any]:
        return {
            "type": "http.request",
            "body": b"--boundary\r\n",
            "more_body": False,
        }

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = cast(int, message["status"])

    scope: MutableMapping[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "scheme": "http",
        "path": "/documents",
        "raw_path": b"/documents",
        "query_string": b"",
        "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    import anyio

    async def exercise_upload_without_content_length() -> None:
        await app(scope, receive, send)

    anyio.run(exercise_upload_without_content_length)

    assert status == 411


def test_upload_rejects_under_declared_body_before_route_logic(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_UPLOAD_BYTES", "64")
    storage = InMemoryDocumentStorage()
    app.state.document_storage = storage
    boundary = "boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="organization_id"\r\n\r\n'
            f"{TENANT_ID}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="workspace_id"\r\n\r\n'
            f"{WORKSPACE_ID}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="agreement.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("ascii")
        + b"%PDF-1.7\nx\r\n"
        + f"--{boundary}--\r\n".encode("ascii")
    )
    status: int | None = None
    midpoint = len(body) // 2
    messages: list[MutableMapping[str, Any]] = [
        {"type": "http.request", "body": body[:midpoint], "more_body": True},
        {"type": "http.request", "body": body[midpoint:], "more_body": False},
    ]

    async def receive() -> MutableMapping[str, Any]:
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = cast(int, message["status"])

    scope: MutableMapping[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "scheme": "http",
        "path": "/documents",
        "raw_path": b"/documents",
        "query_string": b"",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode("ascii")),
            (b"content-length", b"1"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    import anyio

    async def exercise_under_declared_upload() -> None:
        await app(scope, receive, send)

    anyio.run(exercise_under_declared_upload)

    assert status == 413
    assert storage.objects == {}


def test_version_upload_rejects_an_oversized_declared_body_before_multipart_parsing(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_UPLOAD_BYTES", "16")
    status: int | None = None
    received = False

    async def receive() -> MutableMapping[str, Any]:
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = cast(int, message["status"])

    scope: MutableMapping[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "scheme": "http",
        "path": "/agreements/11111111-1111-1111-1111-111111111111/versions",
        "raw_path": b"/agreements/11111111-1111-1111-1111-111111111111/versions",
        "query_string": b"",
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=boundary"),
            (b"content-length", b"17"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    import anyio

    async def exercise_upload() -> None:
        await app(scope, receive, send)

    anyio.run(exercise_upload)

    assert status == 413
    assert received is False


def test_upload_rejects_missing_declared_mime_type() -> None:
    with raises(DocumentValidationError, match="A declared MIME type is required."):
        validate_document(
            filename="agreement.pdf",
            content=b"%PDF-1.7\ncontract",
            declared_content_type=None,
            max_bytes=1024,
        )


def test_upload_requires_authentication() -> None:
    app.dependency_overrides.pop(current_principal)
    correlation_id = "99999999-9999-4999-8999-999999999999"

    response = TestClient(app).post(
        "/documents",
        data=upload_form(),
        headers={"X-Correlation-ID": correlation_id},
        files={"file": ("agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "authentication_required",
        "message": "Authentication required",
        "correlation_id": correlation_id,
    }


def test_upload_rejects_workspace_spoofing_even_when_scope_headers_are_supplied() -> None:
    response = TestClient(app).post(
        "/documents",
        data=upload_form(workspace_id=OTHER_WORKSPACE_ID),
        headers={
            "X-Tenant-ID": TENANT_ID,
            "X-Workspace-ID": WORKSPACE_ID,
        },
        files={"file": ("agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "resource_not_found"}}


def test_authorized_download_returns_the_uploaded_original() -> None:
    storage = InMemoryDocumentStorage()
    app.state.document_storage = storage
    client = TestClient(app)
    created = client.post(
        "/documents",
        data=upload_form(),
        files={"file": ("agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    response = client.get(
        "/documents/download",
        params={
            "organization_id": TENANT_ID,
            "workspace_id": WORKSPACE_ID,
            "object_key": created.json()["object_key"],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"%PDF-1.7\ncontract"


def test_download_rejects_an_object_key_from_another_tenant() -> None:
    storage = InMemoryDocumentStorage()
    app.state.document_storage = storage
    client = TestClient(app)
    created = client.post(
        "/documents",
        data=upload_form(),
        files={"file": ("agreement.pdf", b"%PDF-1.7\ncontract", "application/pdf")},
    )

    response = client.get(
        "/documents/download",
        params={
            "organization_id": TENANT_ID,
            "workspace_id": OTHER_WORKSPACE_ID,
            "object_key": created.json()["object_key"],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "resource_not_found"}}


class RecordingS3Client:
    def __init__(self) -> None:
        self.put_requests: list[dict[str, object]] = []

    def put_object(self, **request: object) -> None:
        self.put_requests.append(request)

    def get_object(self, **request: object) -> Mapping[str, object]:
        return {"Body": BytesIO(b"document"), "ContentType": "application/pdf"}


def test_production_s3_upload_uses_kms_encryption_and_no_overwrite() -> None:
    client = RecordingS3Client()
    storage = S3DocumentStorage(
        client=client,
        bucket="documents",
        production=True,
        kms_key_id="alias/documents",
    )

    created = storage.put_immutable(
        "tenants/t/workspaces/w/documents/a/original.pdf",
        b"document",
        content_type="application/pdf",
        sha256="a" * 64,
    )

    assert created is True
    assert client.put_requests == [
        {
            "Bucket": "documents",
            "Key": "tenants/t/workspaces/w/documents/a/original.pdf",
            "Body": b"document",
            "ContentType": "application/pdf",
            "ChecksumSHA256": "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo=",
            "IfNoneMatch": "*",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "alias/documents",
        }
    ]


def test_s3_precondition_failure_is_reported_as_a_duplicate_without_overwrite() -> None:
    class ExistingObjectS3Client(RecordingS3Client):
        def put_object(self, **request: object) -> None:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")

    storage = S3DocumentStorage(
        client=ExistingObjectS3Client(),
        bucket="documents",
        production=False,
        kms_key_id=None,
    )

    created = storage.put_immutable(
        "tenants/t/workspaces/w/documents/a/original.pdf",
        b"document",
        content_type="application/pdf",
        sha256="a" * 64,
    )

    assert created is False


def test_s3_conditional_request_conflict_is_reported_as_a_duplicate_without_overwrite() -> None:
    class RacingObjectS3Client(RecordingS3Client):
        def put_object(self, **request: object) -> None:
            raise ClientError({"Error": {"Code": "ConditionalRequestConflict"}}, "PutObject")

    storage = S3DocumentStorage(
        client=RacingObjectS3Client(),
        bucket="documents",
        production=False,
        kms_key_id=None,
    )

    created = storage.put_immutable(
        "tenants/t/workspaces/w/documents/a/original.pdf",
        b"document",
        content_type="application/pdf",
        sha256="a" * 64,
    )

    assert created is False
