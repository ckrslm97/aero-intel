import { PivotClient } from "@/components/pivot-client";

export const metadata = {
  title: "Analiz — Pivot Tablo — AeroIntel",
  description:
    "Haber arşivini satır, sütun ve değer atayarak kendi pivot tablona dönüştür.",
};

export default function AnalizPage() {
  return <PivotClient />;
}
