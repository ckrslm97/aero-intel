import { CampaignsClient } from "@/components/campaigns-client";

export const metadata = {
  title: "Kampanyalar — AeroIntel",
  description:
    "Rakip havayollarının satış kampanyaları, taşıyıcı ve zaman ekseninde: canlı, yaklaşan ve sona ermiş satış dönemleri, kaynağıyla birlikte.",
};

export default function CampaignsPage() {
  return <CampaignsClient />;
}
