"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// echarts is ~1.1MB. `fx-forecast-table.tsx` is already a client component, so
// this boundary could technically be declared inline there -- it lives in its
// own module for the same reason `annual-trend-chart-lazy.tsx` does: the chart
// is below the fold and behind a pair selector, and a module boundary keeps it
// out of the chunk the table itself ships in.
//
// The skeleton is 260px to match the chart, so the section does not jump under
// the reader when the real chart arrives.
export const FxForecastChart = dynamic(
  () => import("@/components/kokpit/fx-forecast-chart").then((m) => m.FxForecastChart),
  { ssr: false, loading: () => <Skeleton className="h-[260px] w-full rounded-xl" /> },
);
