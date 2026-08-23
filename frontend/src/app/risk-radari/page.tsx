import { RiskRadarClient } from "@/components/risk-radar-client";

export const metadata = {
  title: "Risk Radarı — AeroIntel",
  description:
    "Haber akışından sınıflandırılmış doğal afet ve çatışma sinyalleri: ülke ve şehir kırılımıyla, operasyonel farkındalık için.",
};

export default function RiskRadarPage() {
  return <RiskRadarClient />;
}
