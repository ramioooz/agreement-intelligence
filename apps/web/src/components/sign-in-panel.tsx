type SignInPanelProps = {
  signInAction: () => void | Promise<void>;
};

export function SignInPanel({ signInAction }: SignInPanelProps) {
  return (
    <main className="mx-auto flex min-h-screen max-w-6xl items-center px-6 py-16">
      <section className="grid gap-10 rounded-[2rem] border border-slate-200 bg-white/85 p-8 shadow-2xl shadow-slate-200/70 backdrop-blur md:grid-cols-[1.1fr_0.9fr] md:p-12">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">
            Agreement Intelligence
          </p>
          <h1 className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
            Sign in to Agreement Intelligence
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-slate-600">
            Review financial agreements with traceable, human-controlled
            intelligence. Start with a secure workspace for repository, reviews,
            search, playbooks, and administration.
          </p>
          <p className="mt-5 max-w-2xl rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
            Your credentials are handled by the identity provider. This
            application keeps provider tokens outside browser JavaScript and
            uses a protected application session after sign-in.
          </p>
        </div>

        <aside className="rounded-3xl bg-slate-950 p-6 text-white">
          <h2 className="text-lg font-semibold">Secure local demo</h2>
          <p className="mt-3 text-sm leading-6 text-slate-300">
            Use a seeded Keycloak user from your local environment. Passwords
            come from your ignored `.env` file.
          </p>
          <form action={signInAction} className="mt-8">
            <button
              className="w-full rounded-full bg-white px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-slate-950"
              type="submit"
            >
              Continue with Keycloak
            </button>
          </form>
        </aside>
      </section>
    </main>
  );
}
