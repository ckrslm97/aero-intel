"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// echarts is already on this page for the map, but the trend chart sits at the
// bottom behind its own fetch and nobody scrolling the country list has needed
// it yet -- so it stays a separate chunk rather than riding along with the
// first paint. Same pattern as kokpit/annual-trend-chart-lazy.tsx.
//
// The skeleton is 280px to match the chart plus its caption, so the section
// does not jump under the reader when the real chart arrives.
export const RiskTrendChart = dynamic(
  () => import("@/components/risk/risk-trend-chart").then((m) => m.RiskTrendChart),
  { ssr: false, loading: () => <Skeleton className="h-[280px] w-full rounded-xl" /> },
);
