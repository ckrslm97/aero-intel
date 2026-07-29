"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";

import {
  baseOption,
  categoryAxis,
  lineGlow,
  useChartTheme,
  valueAxis,
  withAlpha,
} from "@/lib/chart-theme";
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
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();
  const base = baseOption(theme, reduceMotion);

  const byKey = new Map(kpis.map((k) => [k.metric_key, k]));
  const series = REVENUE_BAR_KEYS.map((key) => byKey.get(key)).filter(
    (k): k is KpiOut => k !== undefined,
  );

  if (series.length === 0) return null;

  const hasLastYear = series.some((k) => k.ly_value !== null);
  const hasDelta = series.some((k) => k.ly_delta_pct !== null);
  const unit = series[0].unit;

  const option = {
    ...base,
    grid: { left: 8, right: 8, top: 36, bottom: 8, containLabel: true },
    legend: {
      top: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: theme.ink, fontSize: 11 },
    },
    tooltip: {
      ...base.tooltip,
      trigger: "axis",
      axisPointer: { type: "shadow" },
      valueFormatter: (v: number | null) =>
        v === null || v === undefined ? "—" : formatCompactNumber(v),
    },
    xAxis: {
      ...categoryAxis(theme),
      type: "category",
      data: series.map((k) => k.label),
      axisLabel: {
        color: theme.ink,
        fontSize: 11,
        interval: 0,
        width: 96,
        overflow: "break",
      },
    },
    yAxis: [
      {
        ...valueAxis(theme),
        type: "value",
        name: unit,
        nameTextStyle: { color: theme.ink, fontSize: 10 },
      },
      {
        ...valueAxis(theme),
        type: "value",
        name: "%",
        nameTextStyle: { color: theme.ink, fontSize: 10 },
        splitLine: { show: false },
        axisLabel: { color: theme.ink, fontSize: 11, formatter: (v: number) => `${v}%` },
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
              itemStyle: { color: theme.neutral, borderRadius: [4, 4, 0, 0] },
            },
          ]
        : []),
      {
        name: "2026",
        type: "bar",
        barMaxWidth: 28,
        yAxisIndex: 0,
        data: series.map((k) => k.value),
        label: {
          show: true,
          position: "top",
          color: theme.ink,
          fontSize: 10,
          formatter: (p: { value: number }) => formatCompactNumber(p.value),
        },
        // This year's bars are the lit ones: a vertical gradient from full
        // primary at the cap down toward the axis, so the current year reads
        // as emitting and last year as printed.
        itemStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: theme.primary },
              {
                offset: 1,
                color: withAlpha(theme.primary, theme.isDark ? 0.35 : 0.45),
              },
            ],
          },
          borderRadius: [4, 4, 0, 0],
        },
      },
      ...(hasDelta
        ? [
            {
              name: "Yıllık değişim",
              type: "line",
              yAxisIndex: 1,
              data: series.map((k) => k.ly_delta_pct),
              smooth: true,
              symbol: "circle",
              symbolSize: 7,
              connectNulls: true,
              // The YoY line is the instrument reading over the bars, so it
              // takes the brand amber rather than a second blue.
              lineStyle: lineGlow(theme.signal, theme.isDark),
              itemStyle: {
                color: theme.signal,
                borderColor: theme.surface,
                borderWidth: 2,
              },
              tooltip: {
                valueFormatter: (v: number | null) => (v === null ? "—" : `${v}%`),
              },
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
