import { Plane } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";
import { airlineTabs } from "@/lib/nav";

export default function AirlinesPage() {
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Airline Intelligence
        </h1>
        <p className="text-sm text-muted-foreground">
          Fleet, financial, and network updates by carrier.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {airlineTabs.map((airline) => (
          <div
            key={airline.code}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3"
          >
            <span
              className="flex size-8 items-center justify-center rounded-md text-xs font-bold text-white"
              style={{ backgroundColor: airline.color }}
            >
              {airline.code}
            </span>
            <span className="text-sm font-medium text-card-foreground/80">
              {airline.name}
            </span>
          </div>
        ))}
      </div>
      <ComingSoon
        icon={Plane}
        title="Airline pages are being built"
        description="Brand-themed carrier pages with fleet, financials, and route news land once article ingestion is live."
      />
    </div>
  );
}
