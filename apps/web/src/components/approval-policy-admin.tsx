"use client";

import { useState } from "react";

import type { ApprovalPolicyStage } from "@/lib/approval-api";

export type ApprovalPolicyDraft = {
  name: string;
  agreement_family: "client_agreement" | "liquidity_provider_agreement";
  document_direction: "any" | "first_party" | "counterparty";
  jurisdiction: string;
  materiality: "any" | "low" | "medium" | "high" | "critical";
  precedence: number;
  submitter_may_approve: boolean;
  allow_cross_stage_same_approver: boolean;
  stages: Array<{
    name: string;
    approval_mode: "any" | "all" | "quorum";
    quorum_count: number | null;
    eligible_role_keys: string[];
    eligible_user_ids: string[];
    deadline_hours: number | null;
    escalation_role_key: string | null;
  }>;
};

type ApprovalPolicyAdminProps = {
  policies: Array<{
    id: string;
    policy_id: string;
    name: string;
    version: number;
    status: string;
    jurisdiction: string;
  }>;
  onCreate: (draft: ApprovalPolicyDraft) => Promise<void>;
  onPublish?: (policyId: string, version: number) => Promise<void>;
};

const emptyStage = (name: string): ApprovalPolicyStage => ({
  name,
  approval_mode: "all" as const,
  quorum_count: null,
  eligible_role_keys: [],
  eligible_user_ids: [],
  deadline_hours: 72,
  escalation_role_key: null,
});

export function ApprovalPolicyAdmin({
  policies,
  onCreate,
  onPublish,
}: ApprovalPolicyAdminProps) {
  const [name, setName] = useState("");
  const [agreementFamily, setAgreementFamily] =
    useState<ApprovalPolicyDraft["agreement_family"]>("client_agreement");
  const [jurisdiction, setJurisdiction] = useState("UAE");
  const [stages, setStages] = useState<ApprovalPolicyStage[]>([
    emptyStage("Legal review"),
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string>();
  const [error, setError] = useState<string>();

  async function submit() {
    if (!name.trim()) return;
    setSubmitting(true);
    setMessage(undefined);
    setError(undefined);
    try {
      await onCreate({
        name: name.trim(),
        agreement_family: agreementFamily,
        document_direction: "any",
        jurisdiction: jurisdiction.trim() || "any",
        materiality: "any",
        precedence: 100,
        submitter_may_approve: false,
        allow_cross_stage_same_approver: false,
        stages,
      });
      setMessage("Policy submitted for publication.");
      setName("");
      setStages([emptyStage("Legal review")]);
    } catch {
      setError(
        "The policy could not be saved. Check your access and required fields.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="approval-policy-heading" className="space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">
          Policy administration
        </p>
        <h1
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="approval-policy-heading"
        >
          Approval policies
        </h1>
        <p className="mt-2 text-slate-600">
          Versioned routing rules determine who may approve each review stage.
        </p>
      </header>
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="text-xl font-semibold">Create policy draft</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium">
            Policy name
            <input
              aria-label="Policy name"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Agreement family
            <select
              aria-label="Agreement family"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) =>
                setAgreementFamily(
                  event.target.value as ApprovalPolicyDraft["agreement_family"],
                )
              }
              value={agreementFamily}
            >
              <option value="client_agreement">Client Agreement</option>
              <option value="liquidity_provider_agreement">
                Liquidity Provider Agreement
              </option>
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Jurisdiction
            <input
              aria-label="Jurisdiction"
              className="rounded-lg border border-slate-300 px-3 py-2"
              onChange={(event) => setJurisdiction(event.target.value)}
              value={jurisdiction}
            />
          </label>
          <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
            Routing defaults to precedence 100. Legal and business stages are
            separate by default.
          </p>
        </div>
        <div className="mt-5 space-y-3">
          {stages.map((stage, index) => (
            <div
              className="rounded-xl border border-slate-200 p-4"
              key={`${stage.name}-${index}`}
            >
              <p className="font-semibold">
                Stage {index + 1}: {stage.name}
              </p>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <label className="grid gap-1 text-sm font-medium">
                  Eligible role key
                  <input
                    aria-label={`${stage.name} role`}
                    className="rounded-lg border border-slate-300 px-3 py-2"
                    onChange={(event) =>
                      setStages((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? {
                                ...item,
                                eligible_role_keys: event.target.value.trim()
                                  ? [event.target.value.trim()]
                                  : [],
                              }
                            : item,
                        ),
                      )
                    }
                    placeholder={
                      index === 0 ? "legal_reviewer" : "business_approver"
                    }
                    value={stage.eligible_role_keys[0] ?? ""}
                  />
                </label>
                <label className="grid gap-1 text-sm font-medium">
                  Approval mode
                  <select
                    aria-label={`${stage.name} approval mode`}
                    className="rounded-lg border border-slate-300 px-3 py-2"
                    onChange={(event) =>
                      setStages((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? {
                                ...item,
                                approval_mode: event.target.value as
                                  "any" | "all" | "quorum",
                              }
                            : item,
                        ),
                      )
                    }
                    value={stage.approval_mode}
                  >
                    <option value="all">All approvers</option>
                    <option value="any">Any approver</option>
                    <option value="quorum">Quorum</option>
                  </select>
                </label>
                <label className="grid gap-1 text-sm font-medium">
                  Deadline hours
                  <input
                    aria-label={`${stage.name} deadline`}
                    className="rounded-lg border border-slate-300 px-3 py-2"
                    min={1}
                    onChange={(event) =>
                      setStages((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? {
                                ...item,
                                deadline_hours:
                                  Number(event.target.value) || null,
                              }
                            : item,
                        ),
                      )
                    }
                    type="number"
                    value={stage.deadline_hours ?? ""}
                  />
                </label>
              </div>
            </div>
          ))}
        </div>
        {stages.length === 1 ? (
          <button
            className="mt-4 rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold"
            onClick={() =>
              setStages([...stages, emptyStage("Business approval")])
            }
            type="button"
          >
            Add business stage
          </button>
        ) : null}
        {error ? (
          <p className="mt-4 text-sm font-semibold text-rose-800" role="alert">
            {error}
          </p>
        ) : null}
        {message ? (
          <p
            className="mt-4 text-sm font-semibold text-emerald-800"
            role="status"
          >
            {message}
          </p>
        ) : null}
        <button
          className="mt-5 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={submitting || !name.trim()}
          onClick={submit}
          type="button"
        >
          {submitting ? "Saving…" : "Create policy"}
        </button>
      </section>
      <section
        aria-label="Published and draft policies"
        className="grid gap-4 md:grid-cols-2"
      >
        {policies.map((policy) => (
          <article
            className="rounded-2xl border border-slate-200 bg-white p-5"
            key={policy.id}
          >
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {policy.status}
            </p>
            <h2 className="mt-2 text-lg font-semibold">{policy.name}</h2>
            <p className="mt-1 text-sm text-slate-600">
              Version {policy.version} · {policy.jurisdiction}
            </p>
            {policy.status === "draft" && onPublish ? (
              <button
                className="mt-4 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold"
                onClick={() => onPublish(policy.policy_id, policy.version)}
                type="button"
              >
                Publish version {policy.version}
              </button>
            ) : null}
          </article>
        ))}
      </section>
    </section>
  );
}
