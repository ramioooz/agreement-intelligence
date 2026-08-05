import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import Link from "next/link";

import { auth } from "@/auth";
import { ApprovalReviewWorkspace } from "@/components/approval-review-workspace";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  getFinalReviewPackage,
  getReview,
  getReviewWorkflow,
  listReviewAssignments,
  listReviewComments,
} from "@/lib/approval-api";
import type { AgreementScope } from "@/lib/agreement-api";

function scope(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export default async function ReviewDetailPage({
  params,
}: {
  params: Promise<{ reviewId: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const configuredScope = scope();
  if (!configuredScope) notFound();
  const { reviewId } = await params;
  const token = await getKeycloakAccessToken(await headers());
  let data: {
    review: Awaited<ReturnType<typeof getReview>>;
    comments: Awaited<ReturnType<typeof listReviewComments>>;
    workflow: Awaited<ReturnType<typeof getReviewWorkflow>>;
    finalPackage: Awaited<ReturnType<typeof getFinalReviewPackage>>;
    assignments: Awaited<ReturnType<typeof listReviewAssignments>>;
  } | null = null;
  try {
    const [review, comments, workflow, finalPackage, assignments] =
      await Promise.all([
        getReview({ scope: configuredScope!, token, reviewId }),
        listReviewComments({ scope: configuredScope!, token, reviewId }),
        getReviewWorkflow({ scope: configuredScope!, token, reviewId }),
        getFinalReviewPackage({ scope: configuredScope!, token, reviewId }),
        listReviewAssignments({ scope: configuredScope!, token }),
      ]);
    data = { review, comments, workflow, finalPackage, assignments };
  } catch {
    return (
      <main className="mx-auto max-w-7xl space-y-6 px-6 py-10">
        <Link
          className="text-sm font-semibold text-slate-600 underline-offset-4 hover:underline"
          href="/dashboard/reviews"
        >
          Back to review inbox
        </Link>
        <div
          className="rounded-2xl border border-rose-200 bg-rose-50 p-6"
          role="alert"
        >
          <h1 className="text-xl font-semibold text-rose-950">
            Unable to load this review
          </h1>
          <p className="mt-2 text-rose-900">
            The review may not exist or your workspace does not authorize
            access.
          </p>
        </div>
      </main>
    );
  }
  const workflowValue = data.workflow as {
    id: string;
    state:
      "waiting_for_approval" | "approved" | "rejected" | "revision_requested";
    active_stage_ordinal: number | null;
    revision: number;
    stages?: Array<{ ordinal: number; state: string }>;
  } | null;
  const packageValue = data.finalPackage as {
    pdf_url: string;
    manifest_url: string;
    checksum: string;
    created_at: string;
  } | null;
  const canDecide = data.assignments.some(
    (assignment) =>
      assignment.review_id === data?.review.id &&
      assignment.status === "active",
  );
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <ApprovalReviewWorkspace
        canDecide={canDecide}
        comments={data.comments}
        finalPackage={packageValue}
        review={data.review}
        title={`Review ${data.review.id}`}
        workflow={workflowValue}
      />
    </main>
  );
}
