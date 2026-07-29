"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";

import { formatCompactNumber } from "@/lib/format";
import { REVENUE_BAR_KEYS } from "@/lib/kpi-groups";
import type { KpiOut } from "@/lib/types";

/** Bars: this year vs last year, per revenue line. Line (right axis): the
 * year-on-year change the backend already computes.
 *
 * Everything plotted here is a field of `KpiOut` -- `value`, `ly_value`,
 * `ly_delta_pct`. Nothing is derived, interpolated or invented.
 */
export function RevenueOverviewChart({ kpis }: { kpis: KpiOut[] }) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  // Same theme-aware tokens the insights and KPI-detail charts use.
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";
  const current = isDark ? "#3987e5" : "#2a78d6";
  const lastYear = isDark ? "#4a4a47" : "#c8c7c0";
  const trendLine = isDark ? "#d99b2c" : "#b87d12";

  const byKey = new Map(kpis.map((k) => [k.metric_key, k]));
  const series = REVENUE_BAR_KEYS.map((key) => byKey.get(key)).filter(
    (k): k is KpiOut => k !== undefined,
  );

  if (series.length === 0) return null;

  const hasLastYear = series.some((k) => k.ly_value !== null);
  const hasDelta = series.some((k) => k.ly_delta_pct !== null);
  const unit = series[0].unit;

  const option = {
    grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
    textStyle: { fontFamily: "inherit" },
    legend: {
      top: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: ink, fontSize: 11 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      valueFormatter: (v: number | null) =>
        v === null || v === undefined ? "—" : formatCompactNumber(v),
    },
    xAxis: {
      type: "category",
      data: series.map((k) => k.label),
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11, interval: 0, width: 96, overflow: "break" },
    },
    yAxis: [
      {
        type: "value",
        name: unit,
        nameTextStyle: { color: ink, fontSize: 10 },
        splitLine: { lineStyle: { color: gridline } },
        axisLabel: {
          color: ink,
          fontSize: 11,
          formatter: (v: number) => formatCompactNumber(v),
        },
      },
      {
        type: "value",
        name: "%",
        nameTextStyle: { color: ink, fontSize: 10 },
        splitLine: { show: false },
        axisLabel: { color: ink, fontSize: 11, formatter: (v: number) => `${v}%` },
      },
    ],
    series: [
      ...(hasLastYear
        ? [
            {
              name: "2025",
              type: "bar",
              barMaxWidth: 28,
              yAxisIndex: 0,
              data: series.map((k) => k.ly_value),
              itemStyle: { color: lastYear, borderRadius: [4, 4, 0, 0] },
            },
          ]
        : []),
      {
        name: "2026",
        type: "bar",
        barMaxWidth: 28,
        yAxisIndex: 0,
        data: series.map((k) => k.value),
        itemStyle: { color: current, borderRadius: [4, 4, 0, 0] },
      },
      ...(hasDelta
        ? [
            {
              name: "Yıllık değişim",
              type: "line",
              yAxisIndex: 1,
              data: series.map((k) => k.ly_delta_pct),
              symbol: "circle",
              symbolSize: 7,
              connectNulls: true,
              lineStyle: { width: 2, color: trendLine },
              itemStyle: { color: trendLine, borderColor: surface, borderWidth: 2 },
              tooltip: { valueFormatter: (v: number | null) => (v === null ? "—" : `${v}%`) },
            },
          ]
        : []),
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 300, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
