import http from "k6/http";
import { check } from "k6";
import {
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
    "http_req_duration{operation:repository_read}": ["p(95)<500"],
    "http_req_duration{operation:upload_acceptance}": ["p(95)<1000"],
    checks: ["rate==1"],
  },
};

export function setup() {
  verifyScope();
}

export default function () {
  const repository = http.get(
    `${apiBaseUrl}/agreements?organization_id=${organizationId}&workspace_id=${workspaceId}`,
    { headers: headers(), tags: { operation: "repository_read" } },
  );
  assertAuthorized(repository, "repository read");
  check(repository, {
    "repository contains items": (r) => Array.isArray(r.json("items")),
  });

  if (__ENV.PERFORMANCE_INCLUDE_UPLOAD !== "true") return;
  const payload = {
    organization_id: organizationId,
    workspace_id: workspaceId,
    file: http.file(
      "%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
      "performance.pdf",
      "application/pdf",
    ),
  };
  const uploaded = http.post(`${apiBaseUrl}/documents`, payload, {
    headers: { Authorization: headers().Authorization },
    tags: { operation: "upload_acceptance" },
  });
  assertAuthorized(uploaded, "upload acceptance");
}

export function handleSummary(data) {
  return { stdout: compactSummary(data) + "\n" };
}
