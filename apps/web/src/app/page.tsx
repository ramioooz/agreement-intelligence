import { ApiStatus } from "@/components/api-status";
import { getApiConnectionStatus } from "@/lib/api-health";
import Link from "next/link";

export default async function Home() {
  const apiStatus = await getApiConnectionStatus();

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-6 py-16">
      <p className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">
        Agreement Intelligence
      </p>
      <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
        Review financial agreements with traceable, human-controlled
        intelligence.
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
        The local platform now supports secure sign-in and a protected
        navigation shell. Document workflows will be added in the next delivery
        iterations.
      </p>
      <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center">
        <Link
          className="inline-flex rounded-full bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950 focus:ring-offset-2"
          href="/sign-in"
        >
          Sign in
        </Link>
        <ApiStatus status={apiStatus} />
      </div>
    </main>
  );
}
