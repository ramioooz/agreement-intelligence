from dataclasses import dataclass
from uuid import UUID, uuid5

from agreement_intelligence_api.documents.storage import DocumentStorage, StoredDocument
from agreement_intelligence_api.documents.validation import ValidatedDocument, validate_document

_DOCUMENT_NAMESPACE = UUID("d19da514-a9f8-409f-b882-031450218cb6")


class DocumentAccessDeniedError(PermissionError):
    """A document is outside the requesting tenant and workspace scope."""


class DocumentNotFoundError(LookupError):
    """The requested original document does not exist."""


@dataclass(frozen=True)
class UploadScope:
    tenant_id: UUID
    workspace_id: UUID


@dataclass(frozen=True)
class UploadedDocument:
    document_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    object_key: str
    duplicate: bool


class DocumentService:
    def __init__(self, storage: DocumentStorage, *, max_bytes: int) -> None:
        self._storage = storage
        self._max_bytes = max_bytes

    def upload(
        self,
        scope: UploadScope,
        *,
        filename: str | None,
        content: bytes,
        declared_content_type: str | None,
    ) -> UploadedDocument:
        document = validate_document(
            filename=filename,
            content=content,
            declared_content_type=declared_content_type,
            max_bytes=self._max_bytes,
        )
        key = self._key(scope, document)
        created = self._storage.put_immutable(
            key,
            document.content,
            content_type=document.content_type,
            sha256=document.sha256,
        )
        return UploadedDocument(
            document_id=uuid5(
                _DOCUMENT_NAMESPACE, f"{scope.tenant_id}:{scope.workspace_id}:{document.sha256}"
            ),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            original_filename=document.filename,
            content_type=document.content_type,
            byte_size=len(document.content),
            sha256=document.sha256,
            object_key=key,
            duplicate=not created,
        )

    def download(self, scope: UploadScope, *, object_key: str) -> StoredDocument:
        if not object_key.startswith(self._prefix(scope)):
            raise DocumentAccessDeniedError
        document = self._storage.read(object_key)
        if document is None:
            raise DocumentNotFoundError
        return document

    @staticmethod
    def _prefix(scope: UploadScope) -> str:
        return f"tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/documents/"

    def _key(self, scope: UploadScope, document: ValidatedDocument) -> str:
        return f"{self._prefix(scope)}{document.sha256}/original.{document.extension}"
