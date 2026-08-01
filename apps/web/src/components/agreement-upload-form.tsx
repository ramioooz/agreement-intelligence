"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

type AgreementUploadFormProps = { fetcher?: typeof fetch };

export function AgreementUploadForm({
  fetcher = fetch,
}: AgreementUploadFormProps) {
  const router = useRouter();
  const [message, setMessage] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setSubmitting(true);
    setMessage(undefined);
    const response = await fetcher("/api/agreements/upload", {
      method: "POST",
      body: new FormData(form),
    });
    setSubmitting(false);
    if (response.ok) {
      form.reset();
      router.refresh();
      setMessage("Agreement uploaded.");
      return;
    }
    setMessage("Unable to upload the agreement.");
  }

  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-5"
      id="upload-agreement"
    >
      <h2 className="text-xl font-semibold">Upload agreement</h2>
      <form className="mt-4 grid gap-4" onSubmit={upload}>
        <label className="grid gap-1.5 text-sm font-medium">
          Agreement title
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            name="title"
            required
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Agreement type
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            name="agreementType"
            required
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Original agreement file
          <input
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="rounded-lg border border-slate-300 p-2"
            name="file"
            required
            type="file"
          />
        </label>
        <button
          className="w-fit rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={submitting}
          type="submit"
        >
          {submitting ? "Uploading…" : "Upload agreement"}
        </button>
        {message ? <p role="status">{message}</p> : null}
      </form>
    </section>
  );
}
