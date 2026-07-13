import { Globe2 } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";
import { worldRegions } from "@/lib/nav";

export default function RegionsPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Regional Intelligence
        </h1>
        <p className="text-sm text-muted-foreground">
          News, statistics, and developments by world region.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {worldRegions.map((region) => (
          <div
            key={region.slug}
            className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 text-sm font-medium text-card-foreground/70"
          >
            <Globe2 className="size-4 text-muted-foreground" />
            {region.name}
          </div>
        ))}
      </div>
      <ComingSoon
        icon={Globe2}
        title="Region pages are being built"
        description="Interactive region cards with country/city news, aviation stats, and airport developments land once ingestion is live."
      />
    </div>
  );
}
