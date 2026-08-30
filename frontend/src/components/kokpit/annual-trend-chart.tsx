"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useMemo, useState } from "react";

import {
  areaGlow,
  baseOption,
  categoryAxis,
  lineGlow,
  useChartTheme,
  valueAxis,
} from "@/lib/chart-theme";
import { splitForecast } from "@/lib/cockpit";
import { formatCompactNumber } from "@/lib/format";
import type { AnnualSeries } from "@/lib/types";
import { cn } from "@/lib/utils";

type TabId = "traffic" | "revenue" | "unit";

const TABS: { id: TabId; label: string; keys: string[] }[] = [
  { id: "traffic", label: "Trafik", keys: ["rpk", "ask", "load_factor"] },
  {
    id: "revenue",
    label: "Gelir",
    keys: ["total_aviation_revenue_ytd", "passenger_revenue_ytd", "ancillary_revenue_ytd"],
  },
  { id: "unit", label: "Birim Ekonomi", keys: ["rask", "cask", "yield_per_rpk"] },
];

const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/** IATA's 2019-2026 industry series, three views of it.
 *
 * The forecast tail is drawn dashed rather than being hidden or silently
 * blended into the history: 2026 is a forecast and 2025 an estimate in IATA's
 * June 2026 report, and a solid line through both would claim eight years of
 * measurement where there are six. `splitForecast` (lib/cockpit.ts) is what
 * makes the two halves meet at the last real year instead of leaving a gap.
 *
 * "Doluluk" rides a second axis on the Trafik tab because it is a percentage
 * next to two trillion-scale series; on one axis it would be a flat line on
 * the floor.
 */
export function AnnualTrendChart({ series }: { series: AnnualSeries[] }) {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();
  const [tab, setTab] = useState<TabId>("traffic");

  const byKey = useMemo(() => new Map(series.map((s) => [s.metric_key, s])), [series]);

  const option = useMemo(() => {
    const active = TABS.find((t) => t.id === tab)!;
    const chosen = active.keys
      .map((key) => byKey.get(key))
      .filter((s): s is AnnualSeries => s !== undefined);
    if (chosen.length === 0) return null;

    const years = chosen[0].points.map((point) => point.year);
    const base = baseOption(theme, reduceMotion);
    // The percentage series on the Trafik tab. Everything else on a tab shares
    // a unit by construction (the tab groupings above are unit-coherent).
    const percentKey = tab === "traffic" ? "load_factor" : null;
    const primaryUnit = chosen.find((s) => s.metric_key !== percentKey)?.unit ?? "";

    const echartsSeries = chosen.flatMap((entry, index) => {
      const color = theme.series[index % theme.series.length];
      const onRightAxis = entry.metric_key === percentKey;
      const { actual, projected } = splitForecast(entry.points);
      const shared = {
        type: "line" as const,
        yAxisIndex: onRightAxis ? 1 : 0,
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        connectNulls: false,
        itemStyle: { color, borderColor: theme.surface, borderWidth: 1.5 },
      };
      return [
        {
          ...shared,
          name: entry.label_tr,
          data: actual,
          lineStyle: lineGlow(color, theme.isDark),
          ...(chosen.length === 1 || onRightAxis
            ? {}
            : { areaStyle: { color: areaGlow(color, theme.isDark) } }),
        },
        {
          ...shared,
          // Same legend entry as the solid half, so the legend stays three
          // items rather than six -- `legend.data` below lists only the real
          // names, and this series inherits the toggle by sharing one.
          name: entry.label_tr,
          data: projected,
          lineStyle: { ...lineGlow(color, theme.isDark), type: "dashed" as const, opacity: 0.85 },
          symbol: "emptyCircle",
          tooltip: { show: false },
        },
      ];
    });

    return {
      ...base,
      // right: 24 rather than 8. The last x label sits centred on the final
      // tick at the grid's right edge, and `containLabel` only reserves room
      // for the AXIS labels -- on the two tabs with no right-hand axis to push
      // the grid inward, "2026" was clipped to "202".
      grid: { left: 8, right: 24, top: 34, bottom: 8, containLabel: true },
      legend: {
        top: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        data: chosen.map((entry) => entry.label_tr),
        textStyle: { color: theme.ink, fontSize: 11 },
      },
      tooltip: {
        ...base.tooltip,
        trigger: "axis",
        valueFormatter: (v: number | null) =>
          v === null || v === undefined ? "—" : formatCompactNumber(v),
      },
      xAxis: {
        ...categoryAxis(theme),
        type: "category",
        boundaryGap: false,
        data: years.map(String),
      },
      yAxis: [
        {
          ...valueAxis(theme),
          type: "value",
          scale: true,
          name: primaryUnit,
          nameTextStyle: { color: theme.ink, fontSize: 10 },
        },
        {
          ...valueAxis(theme),
          type: "value",
          scale: true,
          show: percentKey !== null,
          name: percentKey ? "%" : "",
          nameTextStyle: { color: theme.ink, fontSize: 10 },
          splitLine: { show: false },
          axisLabel: { color: theme.ink, fontSize: 11, formatter: (v: number) => `${v}%` },
        },
      ],
      series: echartsSeries,
    };
  }, [tab, byKey, theme, reduceMotion]);

  if (series.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => setTab(entry.id)}
            aria-pressed={tab === entry.id}
            className={chip(tab === entry.id)}
          >
            {entry.label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span aria-hidden className="inline-block h-px w-5 border-t border-dashed border-current" />
          kesikli = tahmin (2025 tahmini gerçekleşme, 2026 tahmin)
        </span>
      </div>
      {option ? (
        <ReactECharts
          option={option}
          style={{ height: 280, width: "100%" }}
          opts={{ renderer: "svg" }}
          notMerge
        />
      ) : (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Bu görünüm için seri yok.
        </p>
      )}
    </div>
  );
}
