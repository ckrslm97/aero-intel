import { RecommendationsClient } from "@/components/recommendations-client";

export const metadata = {
  title: "Öneriler — AeroIntel",
  description:
    "Haber arşivi, yolcu yorumları ve etkinlik takviminden türetilen, kaynağı gösterilen aksiyon önerileri.",
};

export default function RecommendationsPage() {
  return <RecommendationsClient />;
}
