import { Suspense } from "react";

import { RiskRadarClient } from "@/components/risk-radar-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Risk Radarı",
  description:
    "Haber akışından sınıflandırılmış doğal afet ve çatışma sinyalleri: ülke ve şehir kırılımıyla, kaynak kronolojisiyle, operasyonel farkındalık için.",
};

// RiskRadarClient keeps ?days and ?country in the URL so a narrowed view is
// shareable. useSearchParams opts the subtree out of prerendering, so it needs
// its own Suspense boundary -- without one the whole route falls back to
// client-side rendering and the first paint goes blank. Same reason
// app/newspaper/page.tsx has one.
export default function RiskRadarPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
      <RiskRadarClient />
    </Suspense>
  );
}
