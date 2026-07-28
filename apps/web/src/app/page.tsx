import { ApiStatus } from "@/components/api-status";
import { getApiConnectionStatus } from "@/lib/api-health";

export default async function Home() {
  const apiStatus = await getApiConnectionStatus();

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">
        Agreement Intelligence
      </p>
      <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl">
        Review financial agreements with traceable, human-controlled
        intelligence.
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
        The application foundation is running. Document workflows will be added
        in the next delivery iterations.
      </p>
      <div className="mt-8">
        <ApiStatus status={apiStatus} />
      </div>
    </main>
  );
}
