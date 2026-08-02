"use client";

import Link from "next/link";
import { useState } from "react";

import type { PlaybookVersion } from "@/lib/playbook-api";

type LifecycleAction = (formData: FormData) => void | Promise<void>;

type PendingAction =
  | { kind: "archive"; playbookId: string }
  | { kind: "delete-playbook"; playbookId: string }
  | { kind: "delete-version"; playbookId: string; version: number };

export function PlaybookVersionList({
  playbooks,
  currentPlaybookId,
  canManage = false,
  archiveAction,
  deleteDraftVersionAction,
  deletePlaybookAction,
}: {
  playbooks: PlaybookVersion[];
  currentPlaybookId?: string;
  canManage?: boolean;
  archiveAction?: LifecycleAction;
  deleteDraftVersionAction?: LifecycleAction;
  deletePlaybookAction?: LifecycleAction;
}) {
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(
    null,
  );
  const grouped = new Map<string, PlaybookVersion[]>();
  for (const playbook of playbooks) {
    const versions = grouped.get(playbook.playbook_id) ?? [];
    versions.push(playbook);
    grouped.set(playbook.playbook_id, versions);
  }

  return (
    <section aria-labelledby="playbooks-heading" className="space-y-4">
      <div>
        <h1
          className="text-3xl font-semibold tracking-tight"
          id="playbooks-heading"
        >
          Legal playbooks
        </h1>
        <p className="mt-2 text-slate-600">
          Versioned policy rules with explicit routing scope.
        </p>
      </div>
      {grouped.size === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-slate-600">
          No playbooks have been created for this workspace.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {[...grouped.values()].map((versions) => {
            const sortedVersions = [...versions].sort(
              (a, b) => b.version - a.version,
            );
            const newest = sortedVersions[0];
            if (!newest) return null;
            const hasPublished = versions.some(
              (version) => version.status === "published",
            );
            const drafts = versions.filter(
              (version) => version.status === "draft",
            );

            return (
              <article
                aria-label={newest.name}
                className="rounded-2xl border border-slate-200 bg-white p-5"
                key={newest.playbook_id}
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                      {newest.agreement_family.replaceAll("_", " ")}
                    </p>
                    <h2 className="mt-1 text-xl font-semibold">
                      {newest.name}
                    </h2>
                  </div>
                  {canManage &&
                  hasPublished &&
                  drafts.length === 0 &&
                  archiveAction ? (
                    <button
                      className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold hover:bg-slate-50"
                      onClick={() =>
                        setPendingAction({
                          kind: "archive",
                          playbookId: newest.playbook_id,
                        })
                      }
                      type="button"
                    >
                      Archive playbook
                    </button>
                  ) : canManage && !hasPublished && deletePlaybookAction ? (
                    <button
                      className="rounded-full border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50"
                      onClick={() =>
                        setPendingAction({
                          kind: "delete-playbook",
                          playbookId: newest.playbook_id,
                        })
                      }
                      type="button"
                    >
                      Delete playbook
                    </button>
                  ) : null}
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  Direction: {newest.document_direction.replaceAll("_", " ")} ·
                  Jurisdiction: {newest.jurisdiction} · Priority:{" "}
                  {newest.priority}
                </p>
                {canManage && hasPublished && drafts.length > 0 ? (
                  <p className="mt-3 text-sm text-amber-800">
                    Delete all draft versions before archiving this playbook.
                  </p>
                ) : null}
                <ol
                  aria-label={`${newest.name} versions`}
                  className="mt-4 space-y-2"
                >
                  {sortedVersions.map((version) => (
                    <li
                      className="flex items-center justify-between gap-3"
                      key={version.id}
                    >
                      <Link
                        aria-current={
                          version.playbook_id === currentPlaybookId
                            ? "page"
                            : undefined
                        }
                        className="font-semibold underline-offset-4 hover:underline"
                        href={`/dashboard/playbooks/${version.playbook_id}?version=${version.version}`}
                      >
                        Version {version.version}
                      </Link>
                      <div className="flex items-center gap-3">
                        <span
                          className={
                            version.status === "published"
                              ? "rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-900"
                              : version.status === "archived"
                                ? "rounded-full bg-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-700"
                                : "rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900"
                          }
                        >
                          {version.status === "published"
                            ? "Published"
                            : version.status === "archived"
                              ? "Archived"
                              : "Draft"}
                        </span>
                        {canManage &&
                        hasPublished &&
                        version.status === "draft" &&
                        deleteDraftVersionAction ? (
                          <button
                            className="text-sm font-semibold text-rose-800 underline-offset-4 hover:underline"
                            onClick={() =>
                              setPendingAction({
                                kind: "delete-version",
                                playbookId: newest.playbook_id,
                                version: version.version,
                              })
                            }
                            type="button"
                          >
                            Delete draft version {version.version}
                          </button>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
                {pendingAction?.playbookId === newest.playbook_id ? (
                  <LifecycleConfirmationDialog
                    action={pendingAction}
                    archiveAction={archiveAction}
                    deleteDraftVersionAction={deleteDraftVersionAction}
                    deletePlaybookAction={deletePlaybookAction}
                    onCancel={() => setPendingAction(null)}
                  />
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function LifecycleConfirmationDialog({
  action,
  archiveAction,
  deleteDraftVersionAction,
  deletePlaybookAction,
  onCancel,
}: {
  action: PendingAction;
  archiveAction?: LifecycleAction;
  deleteDraftVersionAction?: LifecycleAction;
  deletePlaybookAction?: LifecycleAction;
  onCancel: () => void;
}) {
  const isArchive = action.kind === "archive";
  const isDeleteVersion = action.kind === "delete-version";
  const heading = isArchive
    ? "Archive playbook?"
    : isDeleteVersion
      ? `Delete draft version ${action.version}?`
      : "Delete draft playbook?";
  const confirmationLabel = isArchive
    ? "Archive playbook"
    : isDeleteVersion
      ? "Delete draft version"
      : "Delete playbook";
  const formAction = isArchive
    ? archiveAction
    : isDeleteVersion
      ? deleteDraftVersionAction
      : deletePlaybookAction;

  if (!formAction) return null;

  return (
    <div
      aria-labelledby="playbook-lifecycle-dialog-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"
      role="dialog"
    >
      <form
        action={formAction}
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"
      >
        <input name="playbookId" type="hidden" value={action.playbookId} />
        {isDeleteVersion ? (
          <input name="version" type="hidden" value={action.version} />
        ) : null}
        <h2
          className="text-xl font-semibold"
          id="playbook-lifecycle-dialog-title"
        >
          {heading}
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          {isArchive
            ? "This stops the playbook from being selected for future agreement reviews. Existing history remains available."
            : isDeleteVersion
              ? "This permanently removes the selected draft version. Published versions and their history remain unchanged."
              : "This permanently removes the draft playbook and its draft versions. This cannot be undone."}
        </p>
        <label className="mt-5 grid gap-1.5 text-sm font-medium">
          Reason (optional)
          <textarea
            className="min-h-24 rounded-lg border border-slate-300 px-3 py-2"
            maxLength={1000}
            name="reason"
          />
        </label>
        <div className="mt-6 flex justify-end gap-3">
          <button
            className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
            onClick={onCancel}
            type="button"
          >
            Cancel
          </button>
          <button
            className={
              isArchive
                ? "rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                : "rounded-full bg-rose-700 px-4 py-2 text-sm font-semibold text-white"
            }
            type="submit"
          >
            {confirmationLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
