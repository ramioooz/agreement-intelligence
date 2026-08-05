import { NextRequest } from "next/server";

import { applyRefreshedKeycloakSession, getKeycloakAccessTokenResult } from "@/lib/auth-session-token";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(request: NextRequest, context: { params: Promise<{ reviewId: string }> }) {
  const session = await getKeycloakAccessTokenResult(request.headers);
  if (!session.accessToken) return Response.json({ message: "An authorized session is required." }, { status: 401 });
  const { reviewId } = await context.params;
  const response = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/reviews/${encodeURIComponent(reviewId)}/comments?organization_id=${encodeURIComponent(process.env.API_ORGANIZATION_ID ?? "")}&workspace_id=${encodeURIComponent(process.env.API_WORKSPACE_ID ?? "")}`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${session.accessToken}`, "Content-Type": "application/json" },
    body: await request.text(),
  });
  return applyRefreshedKeycloakSession(new Response(response.body, { status: response.status, headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" } }), session);
}
