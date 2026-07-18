"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";

import { formatPercent } from "@/lib/format";
import type { PortfolioFundOut } from "@/lib/types";

const PALETTE = [
  "#2a78d6", "#1baf7a", "#d98a1b", "#9b5de5", "#e34948",
];

/** Donut of the user's example target allocation for one market portfolio,
 * plus the weighted 1-year return (or an honest "not computable yet" note). */
export function PortfolioAllocationChart({
  funds,
  weightedReturn1yPct,
}: {
  funds: PortfolioFundOut[];
  weightedReturn1yPct: number | null;
}) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";

  const option = {
    tooltip: {
      trigger: "item",
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      valueFormatter: (v: number) => `%${v}`,
    },
    legend: {
      orient: "horizontal",
      bottom: 0,
      textStyle: { color: ink, fontSize: 11 },
    },
    series: [
      {
        type: "pie",
        radius: ["48%", "72%"],
        center: ["50%", "42%"],
        itemStyle: { borderColor: surface, borderWidth: 2 },
        label: {
          show: true,
          color: ink,
          fontSize: 11,
          formatter: "{b}\n%{c}",
        },
        data: funds.map((f, i) => ({
          name: f.symbol,
          value: Math.round(f.target_weight * 100),
          itemStyle: { color: PALETTE[i % PALETTE.length] },
        })),
      },
    ],
  };

  const returnColor =
    weightedReturn1yPct === null
      ? "text-muted-foreground"
      : weightedReturn1yPct >= 0
        ? "text-good"
        : "text-critical";

  return (
    <div className="flex flex-col gap-3">
      <ReactECharts
        option={option}
        style={{ height: 260, width: "100%" }}
        opts={{ renderer: "svg" }}
        notMerge
      />
      <div className="rounded-lg border border-border bg-muted/40 p-3 text-center">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          Ağırlıklı 1 yıllık getiri
        </p>
        {weightedReturn1yPct === null ? (
          <p className="mt-1 text-sm text-muted-foreground">
            Hesaplanamıyor — tüm fonların 1 yıllık verisi henüz tam değil
          </p>
        ) : (
          <p className={`mt-1 text-2xl font-semibold ${returnColor}`}>
            {formatPercent(weightedReturn1yPct)}
          </p>
        )}
      </div>
    </div>
  );
}
