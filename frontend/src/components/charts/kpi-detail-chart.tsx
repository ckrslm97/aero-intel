"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useMemo } from "react";

import {
  areaGlow,
  baseOption,
  categoryAxis,
  lineGlow,
  useChartTheme,
  valueAxis,
} from "@/lib/chart-theme";
import { DISPLAY_TIME_ZONE, formatMetricValue } from "@/lib/format";
import type { KpiHistoryPointOut, KpiPeriod } from "@/lib/types";

interface KpiDetailChartProps {
  history: KpiHistoryPointOut[];
  period: KpiPeriod;
  unit: string;
  /** Which metric these points are, for the precision rule. Optional so a
   * caller with no key still gets the unit-based one, never a crash -- but
   * without it an FX cross is drawn to one decimal, and every gridline
   * between 1,0801 and 1,0899 prints the same "1,1". */
  metricKey?: string;
}

const DATE_FORMAT_BY_PERIOD: Record<KpiPeriod, Intl.DateTimeFormatOptions> = {
  "1w": { weekday: "short", hour: "2-digit" },
  "1m": { month: "short", day: "numeric" },
  "3m": { month: "short", day: "numeric" },
  "6m": { month: "short", day: "numeric" },
  "1y": { month: "short", year: "2-digit" },
};

/** A real chart -- axes, gridlines, tooltip -- for the KPI detail page, as
 * opposed to the decorative sparkline used on the dashboard cards. */
export function KpiDetailChart({ history, period, unit, metricKey }: KpiDetailChartProps) {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();

  // Rebuilt only when the data, the period or the theme actually changes.
  // `notMerge` on the element below makes every fresh object a full chart
  // teardown, so an unmemoized literal cost a rebuild on every parent render.
  const option = useMemo(() => {
    const base = baseOption(theme, reduceMotion);

    // The zone is PINNED, and to the same zone the table under this chart
    // prints (lib/format.ts). Left unpinned it followed the runtime, so the
    // 11:32 UTC reading the history table names sat under a "14:00" bar on the
    // 1w axis three centimetres above it -- one reading, two clocks, one page.
    const dateFormat = { timeZone: DISPLAY_TIME_ZONE, ...DATE_FORMAT_BY_PERIOD[period] };
    const labels = history.map((p) =>
      new Date(p.as_of).toLocaleString("tr-TR", dateFormat),
    );
    const values = history.map((p) => p.value);

    // Same defensive fix as the dashboard sparkline (see charts/sparkline.tsx):
    // a metric that hasn't moved since the last reading has dataMin === dataMax,
    // which can collapse a value axis to zero span. `scale: true` alone is
    // usually robust to this, but computing an explicit padded range removes
    // any doubt and keeps both charts' flat-series behavior identical.
    const dataMin = Math.min(...values);
    const dataMax = Math.max(...values);
    const pad = dataMin === dataMax ? Math.abs(dataMin) * 0.05 || 1 : 0;

    return {
    ...base,
    grid: { left: 8, right: 16, top: 16, bottom: 32, containLabel: true },
    xAxis: {
      ...categoryAxis(theme),
      type: "category",
      data: labels,
      boundaryGap: false,
    },
    yAxis: {
      ...valueAxis(theme),
      type: "value",
      min: dataMin - pad,
      max: dataMax + pad,
      splitLine: { lineStyle: { color: theme.gridline, type: "solid" } },
      axisLabel: {
        color: theme.ink,
        fontSize: 11,
        // The headline above this chart and the axis under it are the same
        // reading; lib/format.ts owns the one rule both print it by.
        formatter: (v: number) => formatMetricValue(v, unit, metricKey),
      },
    },
    tooltip: {
      ...base.tooltip,
      trigger: "axis",
      valueFormatter: (v: number) =>
        `${formatMetricValue(v, unit, metricKey)}${unit ? ` ${unit}` : ""}`,
    },
    series: [
      {
        type: "line",
        data: values,
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false,
        lineStyle: lineGlow(theme.primary, theme.isDark),
        itemStyle: {
          color: theme.primary,
          borderColor: theme.surface,
          borderWidth: 2,
        },
        areaStyle: { color: areaGlow(theme.primary, theme.isDark) },
        emphasis: { focus: "series" },
      },
    ],
    };
  }, [history, period, unit, metricKey, theme, reduceMotion]);

  return (
    <ReactECharts
      option={option}
      style={{ height: 320, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
