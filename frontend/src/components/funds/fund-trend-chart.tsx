"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";

import { formatFundValue } from "@/lib/format";
import type { FundHistoryPointOut, FundPeriod } from "@/lib/types";

interface FundTrendChartProps {
  points: FundHistoryPointOut[];
  period: FundPeriod;
  currency: string;
}

const DATE_FORMAT_BY_PERIOD: Record<FundPeriod, Intl.DateTimeFormatOptions> = {
  "1m": { month: "short", day: "numeric" },
  "3m": { month: "short", day: "numeric" },
  "6m": { month: "short", day: "numeric" },
  "1y": { month: "short", year: "2-digit" },
};

/** 1-year (or shorter) price/NAV line for a fund detail page. Mirrors
 * charts/kpi-detail-chart.tsx theme tokens and its flat-series padding fix. */
export function FundTrendChart({ points, period, currency }: FundTrendChartProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const line = isDark ? "#3987e5" : "#2a78d6";
  const gridline = isDark ? "#2c2c2a" : "#e1e0d9";
  const ink = isDark ? "#c3c2b7" : "#52514e";
  const surface = isDark ? "#1a1a19" : "#fcfcfb";

  const labels = points.map((p) =>
    new Date(p.as_of).toLocaleString("tr-TR", DATE_FORMAT_BY_PERIOD[period]),
  );
  const values = points.map((p) => p.value);

  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const pad = dataMin === dataMax ? Math.abs(dataMin) * 0.05 || 1 : 0;

  const option = {
    grid: { left: 8, right: 16, top: 16, bottom: 32, containLabel: true },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      axisLine: { lineStyle: { color: gridline } },
      axisTick: { show: false },
      axisLabel: { color: ink, fontSize: 11 },
    },
    yAxis: {
      type: "value",
      min: dataMin - pad,
      max: dataMax + pad,
      splitLine: { lineStyle: { color: gridline, type: "solid" } },
      axisLabel: {
        color: ink,
        fontSize: 11,
        formatter: (v: number) => formatFundValue(v, currency),
      },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: surface,
      borderColor: gridline,
      textStyle: { color: isDark ? "#ffffff" : "#0b0b0b", fontSize: 12 },
      valueFormatter: (v: number) => formatFundValue(v, currency),
    },
    series: [
      {
        type: "line",
        data: values,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false,
        lineStyle: { width: 2, color: line },
        itemStyle: { color: line, borderColor: surface, borderWidth: 2 },
        areaStyle: { color: line, opacity: 0.1 },
        emphasis: { focus: "series" },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height: 320, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
