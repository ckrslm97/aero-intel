import { Suspense } from "react";

import { InsightsTabs } from "@/components/insights-tabs";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "İçgörüler",
  description:
    "Haber arşivinden çıkarılan örüntüler ve bu örüntülerden türeyen, kaynağı gösterilen aksiyon önerileri.",
};

// InsightsTabs reads ?tab off the URL so /insights?tab=oneriler deep-links to
// the recommendations (and so /oneriler can redirect there). useSearchParams
// opts the subtree out of prerendering, so it needs its own Suspense boundary
// -- without one the whole route falls back to client-side rendering and the
// first paint goes blank.
export default function InsightsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <InsightsTabs />
    </Suspense>
  );
}
