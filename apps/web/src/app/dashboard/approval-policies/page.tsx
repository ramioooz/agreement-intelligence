import { headers } from "next/headers";
import { redirect } from "next/navigation";
import Link from "next/link";

import { auth } from "@/auth";
import { ApprovalPolicyAdmin } from "@/components/approval-policy-admin";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import { createApprovalPolicy, listApprovalPolicies, publishApprovalPolicy, type ApprovalPolicyDraft } from "@/lib/approval-api";
import type { AgreementScope } from "@/lib/agreement-api";

function scope(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export default async function ApprovalPoliciesPage() {
  if (!(await auth())?.user) redirect("/sign-in?callbackUrl=%2Fdashboard%2Fapproval-policies");
  const configuredScope = scope();
  if (!configuredScope) return <main className="mx-auto max-w-7xl px-6 py-10"><p role="alert">Approval policy administration is not configured.</p></main>;
  const token = await getKeycloakAccessToken(await headers());
  let policies;
  try { policies = await listApprovalPolicies({ scope: configuredScope, token }); } catch { return <main className="mx-auto max-w-7xl space-y-6 px-6 py-10"><Link className="text-sm font-semibold text-slate-600 underline-offset-4 hover:underline" href="/dashboard">Back to dashboard</Link><p className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-rose-900" role="alert">Unable to load approval policies. Check your access and try again.</p></main>; }
  async function create(draft: ApprovalPolicyDraft) {
    "use server";
    await createApprovalPolicy({ scope: configuredScope!, token: await getKeycloakAccessToken(await headers()), draft });
  }
  async function publish(policyId: string, version: number) {
    "use server";
    await publishApprovalPolicy({ scope: configuredScope!, token: await getKeycloakAccessToken(await headers()), policyId, version });
  }
  return <main className="mx-auto max-w-7xl space-y-6 px-6 py-10"><Link className="text-sm font-semibold text-slate-600 underline-offset-4 hover:underline" href="/dashboard">Back to dashboard</Link><ApprovalPolicyAdmin onCreate={create} onPublish={publish} policies={policies} /></main>;
}
