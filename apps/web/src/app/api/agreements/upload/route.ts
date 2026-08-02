import { NextRequest } from "next/server";

import {
  createAgreement,
  uploadDocument,
  type AgreementScope,
} from "@/lib/agreement-api";
import {
  applyRefreshedKeycloakSession,
  getKeycloakAccessTokenResult,
} from "@/lib/auth-session-token";
import { submitProcessingJob } from "@/lib/processing-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export async function POST(request: NextRequest) {
  const scope = scopeFromEnvironment();
  const session = await getKeycloakAccessTokenResult(request.headers);
  const { accessToken: token } = session;
  if (!scope || !token)
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  const form = await request.formData();
  const title = form.get("title");
  const agreementType = form.get("agreementType");
  const documentDirection = form.get("documentDirection");
  const jurisdiction = form.get("jurisdiction");
  const file = form.get("file");
  if (
    typeof title !== "string" ||
    typeof agreementType !== "string" ||
    !(file instanceof File)
  )
    return Response.json(
      { message: "Title, agreement type, and a file are required." },
      { status: 400 },
    );
  try {
    const uploaded = await uploadDocument({ scope, token, file });
    const agreement = await createAgreement({
      scope,
      token,
      agreement: {
        title,
        agreement_type: agreementType,
        status: "draft",
        parties: [],
        files: [
          {
            file_name: uploaded.original_filename,
            content_type: uploaded.content_type,
            storage_key: uploaded.object_key,
            checksum: uploaded.sha256,
            byte_size: uploaded.byte_size,
            version_number: 1,
          },
        ],
        processing_state: "pending",
        audit_metadata: {
          source: "repository-upload",
          document_direction:
            typeof documentDirection === "string" ? documentDirection : "any",
          jurisdiction:
            typeof jurisdiction === "string" && jurisdiction.trim()
              ? jurisdiction.trim().toUpperCase()
              : "any",
        },
      },
    });
    const job = await submitProcessingJob({
      scope,
      token,
      agreementId: agreement.id,
      idempotencyKey: crypto.randomUUID(),
    });
    return applyRefreshedKeycloakSession(
      Response.json(
        { id: agreement.id, processingJobId: job.id },
        { status: 201 },
      ),
      session,
    );
  } catch {
    return Response.json(
      { message: "The agreement could not be uploaded." },
      { status: 502 },
    );
  }
}
