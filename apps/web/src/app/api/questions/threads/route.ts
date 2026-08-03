import { NextRequest } from "next/server";

import { type AgreementScope } from "@/lib/agreement-api";
import { createQuestionThread, type QuestionThread } from "@/lib/question-api";
import {
  applyRefreshedKeycloakSession,
  getKeycloakAccessTokenResult,
} from "@/lib/auth-session-token";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export async function POST(request: NextRequest) {
  const scope = scopeFromEnvironment();
  const session = await getKeycloakAccessTokenResult(request.headers);
  if (!scope || !session.accessToken) {
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  }

  const payload: unknown = await request.json().catch(() => ({}));
  const agreementIds =
    typeof payload === "object" &&
    payload !== null &&
    "agreement_ids" in payload
      ? payload.agreement_ids
      : undefined;
  if (
    agreementIds !== undefined &&
    (!Array.isArray(agreementIds) ||
      agreementIds.some((agreementId) => typeof agreementId !== "string"))
  ) {
    return Response.json(
      { message: "agreement_ids must be an array of strings." },
      { status: 400 },
    );
  }

  try {
    const thread: QuestionThread = await createQuestionThread({
      scope,
      token: session.accessToken,
      agreementIds,
    });
    return applyRefreshedKeycloakSession(
      Response.json(thread, { status: 201 }),
      session,
    );
  } catch {
    return Response.json(
      { message: "Question answering is currently unavailable." },
      { status: 503 },
    );
  }
}
