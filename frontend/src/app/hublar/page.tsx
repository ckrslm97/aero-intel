import { Suspense } from "react";

import { HubsClient } from "@/components/hubs-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Hub",
  description:
    "İzlenen aktarma merkezleri: haber hacmi, üssü orada olan taşıyıcılar, ülke filtresi, dünya haritası ve Ağ Sinyalleri.",
};

// HubsClient keeps its whole view -- tab, hub, window, country, topic -- in the
// URL, so a narrowed hub view is a link and /hublar?view=network-signals is a
// real deep link (İçgörüler points at it). useSearchParams opts the subtree out
// of prerendering, so it needs its own Suspense boundary -- without one the
// whole route falls back to client-side rendering and the first paint goes
// blank. Same reason app/kampanyalar/page.tsx has one.
export default function HubsPage() {
  return (
    <Suspense fallback={<Skeleton className="m-4 h-96 rounded-xl md:m-6" />}>
      <HubsClient />
    </Suspense>
  );
}
