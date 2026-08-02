import { NextRequest } from "next/server";

import { getKeycloakAccessToken } from "@/lib/auth-session-token";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ agreementId: string }> },
) {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  const token = await getKeycloakAccessToken(request.headers);
  if (!organizationId || !workspaceId || !token) {
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  }
  const scope = new URLSearchParams({
    organization_id: organizationId,
    workspace_id: workspaceId,
  });
  const { agreementId } = await context.params;
  const response = await fetch(
    `${apiBaseUrl.replace(/\/$/, "")}/agreements/${encodeURIComponent(agreementId)}/review-report?${scope}`,
    {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    return Response.json(
      { message: "The cited review report is unavailable." },
      { status: response.status },
    );
  }
  return new Response(response.body, {
    headers: {
      "Content-Type": response.headers.get("Content-Type") ?? "application/pdf",
      "Content-Disposition":
        response.headers.get("Content-Disposition") ??
        `attachment; filename="agreement-${agreementId}-review-report.pdf"`,
    },
  });
}
