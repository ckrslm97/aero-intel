"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// echarts is ~1.1MB, app/page.tsx is a Server Component, and `ssr: false` is
// rejected by the compiler inside one ("Please move it into a Client
// Component") -- so the lazy import has to live in a client module of its own
// rather than inline at the call site. Components that are already
// `"use client"` (kokpit/market-pulse-strip.tsx, kokpit/fx-board.tsx) declare
// theirs inline for exactly that reason.
//
// The skeleton is 320px to match the chart plus its tab row, so the section
// does not jump under the reader when the real chart arrives.
export const AnnualTrendChart = dynamic(
  () => import("@/components/kokpit/annual-trend-chart").then((m) => m.AnnualTrendChart),
  { ssr: false, loading: () => <Skeleton className="h-[320px] w-full rounded-xl" /> },
);
