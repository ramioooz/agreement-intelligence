import { headers } from "next/headers";
import { redirect } from "next/navigation";
import Link from "next/link";

import { auth } from "@/auth";
import { ApprovalInbox } from "@/components/approval-inbox";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  getReviewNotifications,
  listReviewAssignments,
} from "@/lib/approval-api";
import type { AgreementScope } from "@/lib/agreement-api";

function scope(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export default async function ReviewsPage() {
  if (!(await auth())?.user)
    redirect("/sign-in?callbackUrl=%2Fdashboard%2Freviews");
  const configuredScope = scope();
  if (!configuredScope)
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <p role="alert">
          A review workspace is not configured. Set the organization and
          workspace identifiers.
        </p>
      </main>
    );
  const token = await getKeycloakAccessToken(await headers());
  let data: Awaited<ReturnType<typeof listReviewAssignments>> | null = null;
  let unreadCount = 0;
  try {
    const [assignments, notifications] = await Promise.all([
      listReviewAssignments({ scope: configuredScope, token }),
      getReviewNotifications({ scope: configuredScope, token }),
    ]);
    data = assignments;
    unreadCount = notifications.unread_count;
  } catch {
    return (
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-10">
        <Link
          className="text-sm font-semibold text-slate-600 underline-offset-4 hover:underline"
          href="/dashboard"
        >
          Back to dashboard
        </Link>
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6">
          <h1 className="text-xl font-semibold text-rose-950">
            Unable to load the review inbox
          </h1>
          <p className="mt-2 text-rose-900">
            Check your access and workspace configuration, then try again.
          </p>
        </div>
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-10">
      <Link
        className="text-sm font-semibold text-slate-600 underline-offset-4 hover:underline"
        href="/dashboard"
      >
        Back to dashboard
      </Link>
      <ApprovalInbox assignments={data ?? []} unreadCount={unreadCount} />
    </main>
  );
}
