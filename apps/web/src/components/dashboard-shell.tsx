import Link from "next/link";

type DashboardUser = {
  email?: string | null;
  name?: string | null;
};

type DashboardShellProps = {
  user: DashboardUser;
  signOutAction: () => void | Promise<void>;
};

const navigationItems: Array<{
  label: string;
  summary: string;
  href?: string;
}> = [
  {
    label: "Repository",
    summary:
      "Upload and browse agreements in the authorized workspace repository.",
    href: "/dashboard/agreements",
  },
  {
    label: "Reviews",
    summary: "Track legal review queues and human decisions in later sprints.",
  },
  {
    label: "Search",
    summary: "Ask cited questions after indexing and retrieval are delivered.",
  },
  {
    label: "Playbooks",
    summary: "Manage clause positions after playbook administration is built.",
  },
  {
    label: "Administration",
    summary: "Configure tenants, users, and policies in later secure stories.",
  },
];

export function DashboardShell({ user, signOutAction }: DashboardShellProps) {
  const displayName = user.name || "Authenticated user";
  const email = user.email || "No email claim provided";

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <header className="border-b border-white/10 bg-slate-950/90 px-6 py-5">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-400">
              Agreement Intelligence
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Agreement workspace
            </h1>
          </div>
          <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm sm:min-w-72">
            <div>
              <p className="font-semibold">{displayName}</p>
              <p className="text-slate-300">{email}</p>
            </div>
            <form action={signOutAction}>
              <button
                className="rounded-full border border-white/20 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white hover:text-slate-950 focus:outline-none focus:ring-2 focus:ring-white"
                type="submit"
              >
                Sign out
              </button>
            </form>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-6 py-10">
        <p className="max-w-3xl text-lg leading-8 text-slate-300">
          You are signed in. Sprint 0 proves protected navigation and secure
          session boundaries; business workflows appear as honest placeholders
          until their delivery stories are implemented.
        </p>

        <nav
          aria-label="Agreement workspace navigation"
          className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-5"
        >
          {navigationItems.map((item) => (
            <article
              aria-label={item.label}
              className="rounded-3xl border border-white/10 bg-white/[0.06] p-5"
              key={item.label}
            >
              <div className="flex items-center justify-between gap-3">
                {item.href ? (
                  <Link
                    className="font-semibold underline-offset-4 hover:underline"
                    href={item.href}
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span className="font-semibold">{item.label}</span>
                )}
                {!item.href ? (
                  <span className="rounded-full bg-amber-300/15 px-2.5 py-1 text-xs font-semibold text-amber-100">
                    Coming soon
                  </span>
                ) : (
                  <span className="rounded-full bg-emerald-300/15 px-2.5 py-1 text-xs font-semibold text-emerald-100">
                    Available
                  </span>
                )}
              </div>
              <p className="mt-4 text-sm leading-6 text-slate-300">
                {item.summary}
              </p>
            </article>
          ))}
        </nav>
      </section>
    </main>
  );
}
