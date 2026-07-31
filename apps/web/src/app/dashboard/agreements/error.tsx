"use client";

export default function AgreementsError({
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <p
        className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900"
        role="alert"
      >
        Unable to load the agreement repository.{" "}
        <button className="underline" onClick={reset} type="button">
          Try again
        </button>
      </p>
    </main>
  );
}
