import http from "k6/http";
import { check, fail } from "k6";
import {
  agreementId,
  apiBaseUrl,
  assertAuthorized,
  compactSummary,
  headers,
  organizationId,
  verifyScope,
  workspaceId,
} from "./common.js";

const skipQuestions = (__ENV.PERFORMANCE_SKIP_QUESTIONS || "false") === "true";

export const options = {
  vus: 1,
  iterations: Number(__ENV.PERFORMANCE_QUESTION_ITERATIONS || 3),
  thresholds: {
    ...(!skipQuestions
      ? {
          "http_req_duration{operation:question_acceptance}": ["p(95)<10000"],
        }
      : {}),
    ...(__ENV.PERFORMANCE_REVIEW_ID
      ? {
          "http_req_duration{operation:workflow_decision_acknowledgement}": [
            "p(95)<1000",
          ],
        }
      : {}),
    checks: ["rate==1"],
  },
};

export function setup() {
  verifyScope();
  let context = {};
  if (!skipQuestions) {
    const response = http.post(
      `${apiBaseUrl}/questions/threads?organization_id=${organizationId}&workspace_id=${workspaceId}`,
      JSON.stringify({ agreement_ids: agreementId ? [agreementId] : [] }),
      { headers: headers(), tags: { operation: "thread_creation" } },
    );
    if (!assertAuthorized(response, "thread creation"))
      fail("thread creation failed");
    context = { threadId: response.json("id") };
  }
  const reviewId = __ENV.PERFORMANCE_REVIEW_ID || "";
  if (skipQuestions && !reviewId)
    fail("PERFORMANCE_REVIEW_ID is required when questions are skipped");
  if (!reviewId) return context;

  const workflow = http.get(
    `${apiBaseUrl}/reviews/${reviewId}/workflow?organization_id=${organizationId}&workspace_id=${workspaceId}`,
    { headers: headers(), tags: { operation: "workflow_read" } },
  );
  if (!assertAuthorized(workflow, "workflow read"))
    fail("workflow read failed");
  if (workflow.json("state") !== "waiting_for_approval")
    fail("workflow is not waiting for approval");
  return {
    ...context,
    reviewId,
    reviewRevision: workflow.json("revision"),
    decisionIdempotencyKey:
      __ENV.PERFORMANCE_WORKFLOW_IDEMPOTENCY_KEY ||
      `performance-decision-${reviewId}`,
  };
}

export default function (context) {
  if (!skipQuestions) {
    const response = http.post(
      `${apiBaseUrl}/questions/threads/${context.threadId}/turns?organization_id=${organizationId}&workspace_id=${workspaceId}`,
      JSON.stringify({
        question:
          "What termination rights are supported by the cited evidence?",
      }),
      { headers: headers(), tags: { operation: "question_acceptance" } },
    );
    assertAuthorized(response, "question acceptance");
    check(response, {
      "question has explicit state": (r) =>
        [
          "answered",
          "partial",
          "insufficient_evidence",
          "conflicting_evidence",
          "model_unavailable",
        ].includes(r.json("answer.status")),
    });
  }

  if (!context.reviewId) return;
  const decision = http.post(
    `${apiBaseUrl}/reviews/${context.reviewId}/workflow/decisions?organization_id=${organizationId}&workspace_id=${workspaceId}`,
    JSON.stringify({
      action: __ENV.PERFORMANCE_WORKFLOW_DECISION || "approve",
      idempotency_key: context.decisionIdempotencyKey,
      expected_revision: context.reviewRevision,
    }),
    {
      headers: headers(),
      tags: { operation: "workflow_decision_acknowledgement" },
    },
  );
  assertAuthorized(decision, "workflow decision acknowledgement");
  check(decision, {
    "workflow decision returns a revision": (r) =>
      Number.isInteger(r.json("revision")),
  });
}

export function handleSummary(data) {
  return { stdout: compactSummary(data) + "\n" };
}
