import { NextRequest } from "next/server";

import {
  applyRefreshedKeycloakSession,
  getKeycloakAccessTokenResult,
} from "@/lib/auth-session-token";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ reviewId: string; artifact: string }> },
) {
  const session = await getKeycloakAccessTokenResult(request.headers);
  if (!session.accessToken)
    return Response.json(
      { message: "An authorized session is required." },
      { status: 401 },
    );
  const { reviewId, artifact } = await context.params;
  if (artifact !== "pdf" && artifact !== "manifest")
    return Response.json({ message: "Not found." }, { status: 404 });
  const response = await fetch(
    `${apiBaseUrl.replace(/\/$/, "")}/reviews/${encodeURIComponent(reviewId)}/final-package/${artifact}`,
    {
      cache: "no-store",
      headers: { Authorization: `Bearer ${session.accessToken}` },
    },
  );
  const extension = artifact === "pdf" ? "pdf" : "json";
  return applyRefreshedKeycloakSession(
    new Response(response.body, {
      status: response.status,
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Disposition":
          response.headers.get("Content-Disposition") ??
          `attachment; filename="review-${reviewId}-final-package.${extension}"`,
        "Content-Type":
          response.headers.get("Content-Type") ?? "application/json",
      },
    }),
    session,
  );
}
