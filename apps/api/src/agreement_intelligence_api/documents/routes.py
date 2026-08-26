import os
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.service import (
    DocumentAccessDeniedError,
    DocumentNotFoundError,
    DocumentService,
    UploadScope,
)
from agreement_intelligence_api.documents.storage import DocumentStorage, storage_from_environment
from agreement_intelligence_api.documents.validation import DocumentValidationError
from agreement_intelligence_api.identity.authz import Principal, current_principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.routes import get_identity_service
from agreement_intelligence_api.identity.service import IdentityService

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
router = APIRouter(prefix="/documents", tags=["documents"])


class UploadResponse(BaseModel):
    document_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    object_key: str
    duplicate: bool


PrincipalDependency = Annotated[Principal, Depends(current_principal)]
IdentityServiceDependency = Annotated[IdentityService, Depends(get_identity_service)]
SessionDependency = Annotated[Session, Depends(get_session)]


def _authorized_scope(
    *,
    principal: Principal,
    identity: IdentityService,
    organization_id: UUID,
    workspace_id: UUID,
    permission: PermissionKey,
) -> UploadScope:
    if not identity.can_access_workspace(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=permission,
    ):
        hide_resource()
    return UploadScope(tenant_id=organization_id, workspace_id=workspace_id)


def get_upload_scope(
    organization_id: Annotated[UUID, Form()],
    workspace_id: Annotated[UUID, Form()],
    principal: PrincipalDependency,
    identity: IdentityServiceDependency,
) -> UploadScope:
    return _authorized_scope(
        principal=principal,
        identity=identity,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=PermissionKey.AGREEMENTS_CREATE,
    )


def get_download_scope(
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
    principal: PrincipalDependency,
    identity: IdentityServiceDependency,
) -> UploadScope:
    return _authorized_scope(
        principal=principal,
        identity=identity,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=PermissionKey.AGREEMENTS_READ,
    )


def get_document_service(request: Request) -> DocumentService:
    storage = getattr(request.app.state, "document_storage", None)
    if storage is None:
        storage = storage_from_environment()
        request.app.state.document_storage = storage
    max_bytes = _configured_max_upload_bytes()
    return DocumentService(cast(DocumentStorage, storage), max_bytes=max_bytes)


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_document(
    response: Response,
    file: Annotated[UploadFile, File()],
    scope: Annotated[UploadScope, Depends(get_upload_scope)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    session: SessionDependency,
) -> UploadResponse:
    try:
        content = await file.read(service._max_bytes + 1)
        document = service.prepare(
            filename=file.filename,
            content=content,
            declared_content_type=file.content_type,
        )
        repository = SQLAlchemyAgreementRepository(session)
        object_key = service.object_key(scope, document)
        repository.lock_source_object(object_key)
        uploaded = service.upload_validated(scope, document)
        repository.record_source_upload(uploaded)
        session.commit()
    except DocumentValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
    if uploaded.duplicate:
        response.status_code = 200
    return UploadResponse.model_validate(uploaded, from_attributes=True)


@router.get("/download")
def download_document(
    object_key: str,
    scope: Annotated[UploadScope, Depends(get_download_scope)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    session: SessionDependency,
) -> StreamingResponse:
    if SQLAlchemyAgreementRepository(session).is_object_pending_deletion(
        object_key,
        organization_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
    ):
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        document = service.download(scope, object_key=object_key)
    except DocumentAccessDeniedError as error:
        raise HTTPException(status_code=403, detail="Document access is not permitted.") from error
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail="Document not found.") from error
    return StreamingResponse(iter([document.content]), media_type=document.content_type)


def _configured_max_upload_bytes() -> int:
    configured = os.environ.get("MAX_DOCUMENT_UPLOAD_BYTES")
    if configured is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        value = int(configured)
    except ValueError as error:
        raise RuntimeError("MAX_DOCUMENT_UPLOAD_BYTES must be an integer.") from error
    if value <= 0:
        raise RuntimeError("MAX_DOCUMENT_UPLOAD_BYTES must be positive.")
    return value
