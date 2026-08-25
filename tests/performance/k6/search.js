import http from "k6/http";
import { check } from "k6";
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
  vus: Number(__ENV.PERFORMANCE_VUS || 2),
  iterations: Number(__ENV.PERFORMANCE_ITERATIONS || 10),
  thresholds: {
    "http_req_duration{operation:filtered_search}": ["p(95)<1000"],
    checks: ["rate==1"],
  },
};

export function setup() {
  verifyScope();
}

export default function () {
  const agreementFilter = agreementId ? `&agreement_id=${agreementId}` : "";
  const response = http.get(
    `${apiBaseUrl}/search?organization_id=${organizationId}&workspace_id=${workspaceId}&query=termination${agreementFilter}`,
    { headers: headers(), tags: { operation: "filtered_search" } },
  );
  assertAuthorized(response, "filtered search");
  check(response, {
    "search contains items": (r) => Array.isArray(r.json("items")),
  });
}

export function handleSummary(data) {
  return { stdout: compactSummary(data) + "\n" };
}
