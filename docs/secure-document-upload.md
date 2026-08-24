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

## Parser resource limits

The compressed document limit is 10 MiB. `MAX_DOCUMENT_UPLOAD_BYTES` can lower
that limit but cannot raise it. DOCX archives are inspected from ZIP metadata
before any entry is expanded: at most 128 entries, 10 MiB per expanded entry,
25 MiB total expanded data, and a 100:1 maximum expansion ratio. Archive member
paths must be relative, unique, and free of traversal; `[Content_Types].xml`,
`_rels/.rels`, and `word/document.xml` are required.

The worker repeats DOCX archive checks for stored or legacy objects and parses
all untrusted PDF and DOCX sources in a spawned child process. The child has a
10-second parent-enforced wall-clock timeout, a 12-second CPU limit, and a
512 MiB address-space limit where the operating system provides these controls;
the parent terminates and, if necessary, kills a timed-out child. PDF parsing is
limited to 250 pages, 20,000 indirect objects, 1,000 root-object recovery and
recursion depth, 10,000 text blocks, and 1,000,000 extracted characters. DOCX extraction has the
same text cap, a 10,000-block cap, and table limits of 2,000 rows and 20,000
cells.

Unsafe, malformed, or timed-out parser inputs become the permanent
`document_parse_rejected` processing failure category with a fixed safe message.
They are not requeued on queue redelivery. The service does not perform malware
scanning; deployment operators must add an external scanning control if that is
required by their policy.

On platforms without the operating-system resource module, parsing relies on
the parent hard timeout because CPU and address-space limits are unavailable.
macOS applies the CPU limit and uses the parent hard timeout for memory because
its spawned interpreter reserves a virtual address space larger than a safe
`RLIMIT_AS` cap. If a required limit is attempted but cannot be applied, the
parser reports temporary unavailability and the job follows the normal retry
policy.

The authentication integration still lives behind #8's `current_principal`
dependency. Until a real OIDC/API-gateway implementation supplies that
principal, the route fails closed with `401`. The download handler additionally
rejects object keys outside the authorized scope.

Presigned upload URLs are intentionally not used in Sprint 1; server-mediated
handling keeps validation and immutable writes in one trusted boundary.
