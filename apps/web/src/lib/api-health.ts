export type ApiConnectionStatus = "connected" | "unavailable";

type HealthPayload = {
  status: "ok";
  service: "api";
  version: string;
};

type HealthOptions = {
  baseUrl?: string;
  fetcher?: typeof fetch;
  timeoutMs?: number;
};

function isHealthPayload(value: unknown): value is HealthPayload {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    payload.status === "ok" &&
    payload.service === "api" &&
    typeof payload.version === "string"
  );
}

export async function getApiConnectionStatus({
  baseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000",
  fetcher = fetch,
  timeoutMs = 1500,
}: HealthOptions = {}): Promise<ApiConnectionStatus> {
  try {
    const response = await fetcher(`${baseUrl}/health/live`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });

    if (!response.ok || !isHealthPayload(await response.json())) {
      return "unavailable";
    }

    return "connected";
  } catch {
    return "unavailable";
  }
}
