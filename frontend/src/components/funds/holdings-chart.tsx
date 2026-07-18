"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";
import { useState } from "react";

import { cn } from "@/lib/utils";
import type { FundHoldingOut } from "@/lib/types";

/** Categorical palette for the treemap -- brand-neutral, distinguishable in both
 * themes; the horizontal bar view uses a single accent so it reads as one series. */
const TREEMAP_COLORS = [
  "#2a78d6", "#1baf7a", "#d98a1b", "#9b5de5", "#e34948",
  "#00a1de", "#c77dff", "#3987e5", "#f4a259", "#5c9ead",
];

type View = "bar" | "treemap";

export function HoldingsChart({
  holdings,
  isTop10Only,
}: {
  holdings: FundHoldingOut[];
  isTop10Only: boolean;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const [view, setView] = useState<View>("bar");

  if (holdings.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Bu fon için henüz pozisyon verisi çekilmedi.
      </p>
    );
  }

  const ink = isDark ? "#c3c2b7" : "#52514e";
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const accent = isDark ? "#3987e5" : "#2a78d6";

  const top10 = [...holdings].slice(0, 10);

  const barOption = {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: "value",
      axisLabel: { color: ink, fontSize: 11, formatter: (v: number) => `%${v}` },
      splitLine: { lineStyle: { color: gridline } },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: top10.map((h) => h.ticker || h.holding_name),
      axisLabel: { color: ink, fontSize: 11 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: gridline } },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      formatter: (params: { dataIndex: number }[]) => {
        const h = top10[params[0].dataIndex];
        return `${h.holding_name}${h.ticker ? ` (${h.ticker})` : ""}<br/>%${h.weight_pct.toFixed(2)}`;
      },
    },
    series: [
      {
        type: "bar",
        data: top10.map((h) => h.weight_pct),
        itemStyle: { color: accent, borderRadius: [0, 3, 3, 0] },
        barWidth: "62%",
      },
    ],
  };

  const treemapOption = {
    tooltip: {
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      formatter: (info: { name: string; value: number; data: { ticker?: string } }) =>
        `${info.name}${info.data.ticker ? ` (${info.data.ticker})` : ""}<br/>%${info.value.toFixed(2)}`,
    },
    series: [
      {
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: { show: true, color: "#ffffff", fontSize: 11, formatter: "{b}" },
        itemStyle: { borderColor: surface, borderWidth: 2, gapWidth: 2 },
        data: holdings.map((h, i) => ({
          name: h.ticker || h.holding_name,
          value: h.weight_pct,
          ticker: h.ticker ?? undefined,
          itemStyle: { color: TREEMAP_COLORS[i % TREEMAP_COLORS.length] },
        })),
      },
    ],
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-muted-foreground">
          {isTop10Only
            ? "Yalnızca ilk 10 pozisyon (tek kaynak)"
            : `${holdings.length} pozisyon`}
        </span>
        <div className="flex gap-1 rounded-lg border border-border p-0.5">
          {(["bar", "treemap"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                view === v
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              {v === "bar" ? "İlk 10" : "Tümü"}
            </button>
          ))}
        </div>
      </div>
      <ReactECharts
        option={view === "bar" ? barOption : treemapOption}
        style={{ height: view === "bar" ? 340 : 380, width: "100%" }}
        opts={{ renderer: "svg" }}
        notMerge
      />
    </div>
  );
}
