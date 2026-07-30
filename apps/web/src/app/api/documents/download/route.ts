import { NextRequest } from "next/server";

import { getKeycloakAccessToken } from "@/lib/auth-session-token";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(request: NextRequest) {
  const objectKey = request.nextUrl.searchParams.get("object_key");
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");
  if (!objectKey || !organizationId || !workspaceId)
    return Response.json(
      { message: "A document scope is required." },
      { status: 400 },
    );
  const accessToken = await getKeycloakAccessToken(request.headers);
  if (!accessToken)
    return Response.json(
      { message: "Sign in is required to download documents." },
      { status: 401 },
    );
  const query = new URLSearchParams({
    object_key: objectKey,
    organization_id: organizationId,
    workspace_id: workspaceId,
  });
  const response = await fetch(
    `${apiBaseUrl.replace(/\/$/, "")}/documents/download?${query}`,
    { cache: "no-store", headers: { Authorization: `Bearer ${accessToken}` } },
  );
  if (!response.ok)
    return Response.json(
      { message: "The requested document is unavailable." },
      { status: response.status },
    );
  return new Response(response.body, {
    headers: {
      "Content-Type":
        response.headers.get("Content-Type") ?? "application/octet-stream",
      "Content-Disposition":
        response.headers.get("Content-Disposition") ?? "inline",
    },
  });
}
