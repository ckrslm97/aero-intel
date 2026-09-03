import { Suspense } from "react";

import { RiskVerificationClient } from "@/components/risk-verification-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Risk Radarı — Veri doğrulama",
  description:
    "Risk Radarı'nın huni sayıları ve reddedilen adaylar: hangi haber hangi kural yüzünden listede yok, hangi değerlerle.",
};

/** The audit view behind /risk-radari.
 *
 * It has a Suspense boundary now, like the radar's own page: this client reads
 * ?days (and carries ?country back) so the funnel audits the same window the
 * radar was showing, and useSearchParams opts the subtree out of prerendering.
 * Without the boundary the whole route falls back to client-side rendering and
 * the first paint goes blank.
 */
export default function RiskVerificationPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <RiskVerificationClient />
    </Suspense>
  );
}
