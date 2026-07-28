import type { ApiConnectionStatus } from "@/lib/api-health";

type ApiStatusProps = {
  status: ApiConnectionStatus;
};

export function ApiStatus({ status }: ApiStatusProps) {
  const connected = status === "connected";

  return (
    <p
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-medium ${
        connected
          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-amber-200 bg-amber-50 text-amber-900"
      }`}
      role="status"
    >
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${
          connected ? "bg-emerald-500" : "bg-amber-500"
        }`}
      />
      {connected ? "API connected" : "API unavailable"}
    </p>
  );
}
