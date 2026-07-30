# Secure document uploads

The API provides a server-mediated upload flow at `POST /documents` and a
server-mediated original download flow at `GET /documents/download`. Files never
receive a public object-store URL in this flow.

Uploads require an authenticated principal. The client names the target
organization and workspace, and the API authorizes that target with
`IdentityService.can_access_workspace` before deriving storage scope. Uploads
require `agreements:create`; downloads require `agreements:read`. Supplying
tenant or workspace headers does not grant access.

Uploads accept only PDF and DOCX originals. The API rejects missing declared
upload lengths and counts received upload bytes before multipart parsing, so
oversized, chunked, or under-declared request bodies do not reach route logic.
It then verifies the file extension, declared MIME type, file signature,
configurable file size limit, and SHA-256 checksum before writing to object
storage. Each object key is deterministic and scoped to the tenant and
workspace:

`tenants/{tenant_id}/workspaces/{workspace_id}/documents/{sha256}/original.{extension}`

The S3 adapter sends `If-None-Match: *`, so the deterministic original cannot be
overwritten. A repeated upload or conditional-write race with the same content
and scope returns the same document reference with `duplicate: true`. Production
mode (`APP_ENV=production`) uses S3 SSE-KMS, optionally selecting
`S3_DOCUMENT_KMS_KEY_ID`.

The authentication integration still lives behind #8's `current_principal`
dependency. Until a real OIDC/API-gateway implementation supplies that
principal, the route fails closed with `401`. The download handler additionally
rejects object keys outside the authorized scope.

Presigned upload URLs are intentionally not used in Sprint 1; server-mediated
handling keeps validation and immutable writes in one trusted boundary.
