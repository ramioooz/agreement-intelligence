import { AgreementRepository } from "@/components/agreement-repository";

export default function AgreementsLoading() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <AgreementRepository state="loading" />
    </main>
  );
}
