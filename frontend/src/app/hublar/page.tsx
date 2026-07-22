import { HubsClient } from "@/components/hubs-client";

export const metadata = {
  title: "Hub'lar — AeroIntel",
  description:
    "İzlenen aktarma merkezleri: haber hacmi, üssü orada olan taşıyıcılar, ülke filtresi ve dünya haritası.",
};

export default function HubsPage() {
  return <HubsClient />;
}
