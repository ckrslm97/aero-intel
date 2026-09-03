import { RiskVerificationClient } from "@/components/risk-verification-client";

export const metadata = {
  title: "Risk Radarı — Veri doğrulama — AeroIntel",
  description:
    "Risk Radarı'nın huni sayıları ve reddedilen adaylar: hangi haber hangi kural yüzünden listede yok, hangi değerlerle.",
};

/** The audit view behind /risk-radari.
 *
 * No Suspense boundary here, unlike the radar's own page: this client reads no
 * search params, so nothing in its subtree opts out of prerendering. The two
 * fetches it makes are ordinary client-side sources with their own skeletons.
 */
export default function RiskVerificationPage() {
  return <RiskVerificationClient />;
}
