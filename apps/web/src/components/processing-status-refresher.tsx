"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import type { ProcessingState } from "@/lib/agreement-api";

const REFRESH_INTERVAL_MS = 2_000;

function isActive(state: ProcessingState | undefined): boolean {
  return state === "queued" || state === "processing";
}

export function ProcessingStatusRefresher({
  state,
}: {
  state: ProcessingState | undefined;
}) {
  const router = useRouter();
  const active = isActive(state);

  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(
      () => router.refresh(),
      REFRESH_INTERVAL_MS,
    );
    return () => window.clearInterval(interval);
  }, [active, router]);

  if (!active) return null;
  return (
    <p className="sr-only" role="status">
      Refreshing analysis status.
    </p>
  );
}
