"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";

import type { FundAllocationOut } from "@/lib/types";

const PALETTE = [
  "#2a78d6", "#1baf7a", "#d98a1b", "#9b5de5", "#e34948",
  "#00a1de", "#c77dff", "#f4a259", "#5c9ead", "#8ac926",
];

/** Donut of sector (US) or asset-class (TR) allocation. */
export function AllocationPie({
  allocations,
  title,
}: {
  allocations: FundAllocationOut[];
  title?: string;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  if (allocations.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Dağılım verisi henüz çekilmedi.
      </p>
    );
  }

  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";

  const option = {
    tooltip: {
      trigger: "item",
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      valueFormatter: (v: number) => `%${v.toFixed(2)}`,
    },
    legend: {
      type: "scroll",
      orient: "horizontal",
      bottom: 0,
      textStyle: { color: ink, fontSize: 11 },
    },
    series: [
      {
        type: "pie",
        radius: ["45%", "70%"],
        center: ["50%", "44%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: surface, borderWidth: 2 },
        label: { show: false },
        labelLine: { show: false },
        data: allocations.map((a, i) => ({
          name: a.label,
          value: a.weight_pct,
          itemStyle: { color: PALETTE[i % PALETTE.length] },
        })),
      },
    ],
  };

  return (
    <div className="flex flex-col gap-2">
      {title && (
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h3>
      )}
      <ReactECharts
        option={option}
        style={{ height: 300, width: "100%" }}
        opts={{ renderer: "svg" }}
        notMerge
      />
    </div>
  );
}
