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

export const options = {
  vus: 1,
  iterations: Number(__ENV.PERFORMANCE_QUESTION_ITERATIONS || 3),
  thresholds: {
    "http_req_duration{operation:question_acceptance}": ["p(95)<10000"],
    checks: ["rate==1"],
  },
};

export function setup() {
  verifyScope();
  const response = http.post(
    `${apiBaseUrl}/questions/threads?organization_id=${organizationId}&workspace_id=${workspaceId}`,
    JSON.stringify({ agreement_ids: agreementId ? [agreementId] : [] }),
    { headers: headers(), tags: { operation: "thread_creation" } },
  );
  if (!assertAuthorized(response, "thread creation"))
    fail("thread creation failed");
  return { threadId: response.json("id") };
}

export default function (context) {
  const response = http.post(
    `${apiBaseUrl}/questions/threads/${context.threadId}/turns?organization_id=${organizationId}&workspace_id=${workspaceId}`,
    JSON.stringify({
      question: "What termination rights are supported by the cited evidence?",
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

export function handleSummary(data) {
  return { stdout: compactSummary(data) + "\n" };
}
