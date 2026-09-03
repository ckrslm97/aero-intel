import { HubsClient } from "@/components/hubs-client";

export const metadata = {
  title: "Hub",
  description:
    "İzlenen aktarma merkezleri: haber hacmi, üssü orada olan taşıyıcılar, ülke filtresi, dünya haritası ve Ağ Sinyalleri.",
};

export default function HubsPage() {
  return <HubsClient />;
}
