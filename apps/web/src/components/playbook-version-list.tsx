import Link from "next/link";

import type { PlaybookVersion } from "@/lib/playbook-api";

export function PlaybookVersionList({
  playbooks,
  currentPlaybookId,
}: {
  playbooks: PlaybookVersion[];
  currentPlaybookId?: string;
}) {
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
            const newest = [...versions].sort(
              (a, b) => b.version - a.version,
            )[0];
            if (!newest) return null;
            return (
              <article
                className="rounded-2xl border border-slate-200 bg-white p-5"
                key={newest.playbook_id}
              >
                <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {newest.agreement_family.replaceAll("_", " ")}
                </p>
                <h2 className="mt-1 text-xl font-semibold">{newest.name}</h2>
                <p className="mt-2 text-sm text-slate-600">
                  Direction: {newest.document_direction.replaceAll("_", " ")} ·
                  Jurisdiction: {newest.jurisdiction} · Priority:{" "}
                  {newest.priority}
                </p>
                <ol
                  aria-label={`${newest.name} versions`}
                  className="mt-4 space-y-2"
                >
                  {[...versions]
                    .sort((a, b) => b.version - a.version)
                    .map((version) => (
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
                      </li>
                    ))}
                </ol>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
