import { NextRequest } from "next/server";

import { deleteAgreement, type AgreementScope } from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ agreementId: string }> },
) {
  const scope = scopeFromEnvironment();
  const token = await getKeycloakAccessToken(request.headers);
  if (!scope || !token) {
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  }
  try {
    await deleteAgreement({
      scope,
      agreementId: (await context.params).agreementId,
      token,
    });
    return new Response(null, { status: 204 });
  } catch {
    return Response.json(
      { message: "The agreement could not be deleted." },
      { status: 502 },
    );
  }
}
