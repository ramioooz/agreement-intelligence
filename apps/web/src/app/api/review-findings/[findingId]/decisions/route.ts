import { NextRequest } from "next/server";

import {
  applyRefreshedKeycloakSession,
  getKeycloakAccessTokenResult,
} from "@/lib/auth-session-token";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function configuredScope(): URLSearchParams | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId
    ? new URLSearchParams({
        organization_id: organizationId,
        workspace_id: workspaceId,
      })
    : null;
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ findingId: string }> },
) {
  const scope = configuredScope();
  const session = await getKeycloakAccessTokenResult(request.headers);
  const { accessToken: token } = session;
  if (!scope || !token) {
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  }
  const { findingId } = await context.params;
  const response = await fetch(
    `${apiBaseUrl.replace(/\/$/, "")}/review-findings/${encodeURIComponent(findingId)}/decisions?${scope}`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: await request.text(),
    },
  );
  return applyRefreshedKeycloakSession(
    new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("Content-Type") ?? "application/json",
      },
    }),
    session,
  );
}
