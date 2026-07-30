"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// Same reasoning as the Sparkline in components/kpi-card.tsx: echarts is
// ~1.1MB and this is the dashboard's only chart, so a static import from
// app/page.tsx put the entire charting library in the landing page's initial
// bundle -- precisely what the Sparkline's dynamic import exists to avoid.
//
// This indirection is not decoration. `ssr: false` is rejected by the compiler
// inside a Server Component ("Please move it into a Client Component"), and
// app/page.tsx is one, so the lazy boundary has to live in a client module of
// its own. kpi-card.tsx and newspaper-browser.tsx get to declare theirs inline
// only because both are already `"use client"` themselves.
//
// The skeleton matches the chart's rendered height (300px) so the card does
// not resize under the reader when the real chart arrives.
export const RevenueOverviewChart = dynamic(
  () =>
    import("@/components/revenue-overview-chart").then(
      (m) => m.RevenueOverviewChart,
    ),
  { ssr: false, loading: () => <Skeleton className="h-[300px] w-full rounded-xl" /> },
);
