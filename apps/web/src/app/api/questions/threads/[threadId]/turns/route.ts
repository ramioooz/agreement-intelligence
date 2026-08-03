import { NextRequest } from "next/server";

import { type AgreementScope } from "@/lib/agreement-api";
import { askQuestion, type QuestionTurn } from "@/lib/question-api";
import {
  applyRefreshedKeycloakSession,
  getKeycloakAccessTokenResult,
} from "@/lib/auth-session-token";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ threadId: string }> },
) {
  const scope = scopeFromEnvironment();
  const session = await getKeycloakAccessTokenResult(request.headers);
  const payload = (await request.json().catch(() => null)) as {
    question?: unknown;
  } | null;
  if (!scope || !session.accessToken) {
    return Response.json(
      { message: "An authorized workspace session is required." },
      { status: 401 },
    );
  }
  if (typeof payload?.question !== "string" || !payload.question.trim()) {
    return Response.json(
      { message: "A question is required." },
      { status: 400 },
    );
  }
  try {
    const turn: QuestionTurn = await askQuestion({
      scope,
      token: session.accessToken,
      threadId: (await context.params).threadId,
      question: payload.question.trim(),
    });
    return applyRefreshedKeycloakSession(
      Response.json(turn, { status: 201 }),
      session,
    );
  } catch {
    return Response.json(
      { message: "Question answering is currently unavailable." },
      { status: 503 },
    );
  }
}
