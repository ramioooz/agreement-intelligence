import { ReviewWorkspace } from "@/components/review-workspace";

export default function AgreementReviewLoading() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <ReviewWorkspace agreementId="" agreementTitle="" state="loading" />
    </main>
  );
}
