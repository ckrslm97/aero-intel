import { Suspense } from "react";

import { CampaignsClient } from "@/components/campaigns-client";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata = {
  title: "Kampanyalar",
  description:
    "Rakip havayollarının satış kampanyaları: satış ve seyahat dönemleri ayrı ayrı, bitmek üzere olanlar önde, kaynağıyla birlikte.",
};

// CampaignsClient keeps the whole filter state in the URL so a narrowed view
// is a link. useSearchParams opts the subtree out of prerendering, so it needs
// its own Suspense boundary -- without one the whole route falls back to
// client-side rendering and the first paint goes blank. Same reason
// app/risk-radari/page.tsx has one.
export default function CampaignsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 rounded-lg" />}>
      <CampaignsClient />
    </Suspense>
  );
}
