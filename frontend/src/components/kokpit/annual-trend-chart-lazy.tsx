"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// echarts is ~1.1MB, app/page.tsx is a Server Component, and `ssr: false` is
// rejected by the compiler inside one ("Please move it into a Client
// Component") -- so the lazy import has to live in a client module of its own
// rather than inline at the call site. Components that are already
// `"use client"` (kokpit/fx-board-table.tsx) declare theirs inline for exactly
// that reason.
//
// The skeleton is 240px, matching the chart, so the section does not jump
// under the reader when the real chart arrives.
export const AnnualTrendChart = dynamic(
  () => import("@/components/kokpit/annual-trend-chart").then((m) => m.AnnualTrendChart),
  { ssr: false, loading: () => <Skeleton className="h-[240px] w-full rounded-xl" /> },
);
