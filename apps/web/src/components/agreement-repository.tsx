"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AgreementStatus, AgreementSummary } from "@/lib/agreement-api";

type RepositoryFilters = {
  query: string;
  status: AgreementStatus | "all";
  agreementType: string;
};

type AgreementRepositoryProps = {
  agreements?: AgreementSummary[];
  nextCursor?: string | null;
  filters?: RepositoryFilters;
  state?: "loading" | "error";
  canDelete?: boolean;
};

const statuses: Array<AgreementStatus | "all"> = [
  "all",
  "draft",
  "active",
  "expired",
  "terminated",
];

function searchParams(filters: RepositoryFilters, cursor?: string): string {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  if (filters.status !== "all") params.set("status", filters.status);
  if (filters.agreementType !== "all")
    params.set("type", filters.agreementType);
  if (cursor) params.set("cursor", cursor);
  const search = params.toString();
  return search ? `?${search}` : "";
}

export function AgreementRepository({
  agreements = [],
  nextCursor = null,
  filters = { query: "", status: "all", agreementType: "all" },
  state,
  canDelete = false,
}: AgreementRepositoryProps) {
  const router = useRouter();
  const [deletingId, setDeletingId] = useState<string>();
  const [deleteError, setDeleteError] = useState<string>();

  async function deleteAgreement(id: string, title: string) {
    if (
      !window.confirm(`Permanently delete “${title}”? This cannot be undone.`)
    )
      return;
    setDeleteError(undefined);
    setDeletingId(id);
    try {
      const response = await fetch(`/api/agreements/${id}`, {
        method: "DELETE",
      });
      if (response.ok) {
        router.refresh();
      } else {
        setDeleteError(
          "Unable to permanently delete the agreement. Please try again.",
        );
      }
    } catch {
      setDeleteError(
        "Unable to permanently delete the agreement. Please try again.",
      );
    } finally {
      setDeletingId(undefined);
    }
  }
  if (state === "loading") {
    return (
      <p
        className="rounded-xl border border-slate-200 bg-white p-6 text-slate-600"
        role="status"
      >
        Loading agreements…
      </p>
    );
  }
  if (state === "error") {
    return (
      <p
        className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900"
        role="alert"
      >
        Unable to load the agreement repository. Check your access and try
        again.
      </p>
    );
  }

  return (
    <section aria-labelledby="repository-heading" className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link
            className="mb-3 inline-flex text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
            href="/dashboard"
          >
            Back to dashboard
          </Link>
          <h1
            className="text-3xl font-semibold tracking-tight"
            id="repository-heading"
          >
            Agreement repository
          </h1>
          <p className="mt-2 text-slate-600">
            Browse the agreements your workspace authorizes you to access.
          </p>
        </div>
        <Link
          className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
          href="#upload-agreement"
        >
          Upload agreement
        </Link>
      </div>
      <form
        className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-3"
        method="get"
      >
        <label className="grid gap-1.5 text-sm font-medium">
          Search agreements
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            defaultValue={filters.query}
            name="q"
            placeholder="Title"
            type="search"
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Agreement status
          <select
            className="rounded-lg border border-slate-300 px-3 py-2"
            defaultValue={filters.status}
            name="status"
          >
            {statuses.map((status) => (
              <option key={status} value={status}>
                {status === "all" ? "All statuses" : status}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Agreement type
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            defaultValue={
              filters.agreementType === "all" ? "" : filters.agreementType
            }
            name="type"
            placeholder="Any type"
          />
        </label>
        <button
          className="w-fit rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
          type="submit"
        >
          Apply filters
        </button>
      </form>
      {agreements.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-slate-600">
          No agreements match the current filters.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table
            aria-label="Agreement repository"
            className="w-full min-w-[760px] text-left text-sm"
          >
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3">Agreement</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Processing</th>
                <th className="px-4 py-3">Updated</th>
                {canDelete ? <th className="px-4 py-3">Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {agreements.map((agreement) => (
                <tr
                  className="border-b border-slate-100 last:border-0"
                  key={agreement.id}
                >
                  <td className="px-4 py-3 font-semibold">
                    <Link
                      className="underline-offset-4 hover:underline"
                      href={`/dashboard/agreements/${agreement.id}`}
                    >
                      {agreement.title}
                    </Link>
                    <p className="mt-1 font-normal text-slate-500">
                      {agreement.parties
                        .map((party) => party.name)
                        .join(", ") || "No parties recorded"}
                    </p>
                  </td>
                  <td className="px-4 py-3">{agreement.agreement_type}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-1 font-medium">
                      {agreement.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">{agreement.processing_state}</td>
                  <td className="px-4 py-3">
                    {new Date(agreement.updated_at).toLocaleDateString()}
                  </td>
                  {canDelete ? (
                    <td className="px-4 py-3">
                      <button
                        className="rounded-full border border-rose-300 px-3 py-1.5 font-semibold text-rose-800 disabled:opacity-60"
                        disabled={deletingId === agreement.id}
                        onClick={() =>
                          void deleteAgreement(agreement.id, agreement.title)
                        }
                        type="button"
                      >
                        {deletingId === agreement.id ? "Deleting…" : "Delete"}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav aria-label="Repository pagination" className="flex justify-end">
        {nextCursor ? (
          <Link
            className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
            href={`/dashboard/agreements${searchParams(filters, nextCursor)}`}
          >
            Next page
          </Link>
        ) : (
          <span className="text-sm text-slate-500">End of repository</span>
        )}
      </nav>
      {deleteError ? (
        <p
          className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-900"
          role="alert"
        >
          {deleteError}
        </p>
      ) : null}
    </section>
  );
}
