import http from "k6/http";
import { check, fail } from "k6";

export const apiBaseUrl = __ENV.PERFORMANCE_API_BASE_URL || "http://api:8000";
export const organizationId = required("PERFORMANCE_ORGANIZATION_ID");
export const workspaceId = required("PERFORMANCE_WORKSPACE_ID");
export const agreementId = __ENV.PERFORMANCE_AGREEMENT_ID || "";

export function required(name) {
  const value = __ENV[name];
  if (!value) fail(`${name} is required`);
  return value;
}

export function headers() {
  return {
    Authorization: `Bearer ${required("PERFORMANCE_ACCESS_TOKEN")}`,
    "Content-Type": "application/json",
  };
}

export function assertAuthorized(response, label) {
  return check(response, {
    [`${label}: authorized success`]: (r) => r.status >= 200 && r.status < 300,
    [`${label}: JSON response`]: (r) =>
      (r.headers["Content-Type"] || "").includes("application/json"),
  });
}

export function verifyScope() {
  const response = http.get(
    `${apiBaseUrl}/identity/organizations/${organizationId}/workspaces/${workspaceId}/capabilities`,
    { headers: headers(), tags: { operation: "tenant_scope_check" } },
  );
  if (!assertAuthorized(response, "tenant scope"))
    fail("tenant scope validation failed");
}

export function compactSummary(data) {
  const metrics = {};
  for (const [name, metric] of Object.entries(data.metrics)) {
    if (!name.startsWith("http_req_duration") && !name.startsWith("checks"))
      continue;
    metrics[name] = metric.values;
  }
  return JSON.stringify({ root_group: data.root_group.name, metrics }, null, 2);
}
