"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useMemo } from "react";

import { areaGlow, baseOption, categoryAxis, useChartTheme, valueAxis } from "@/lib/chart-theme";
import { splitForecast, unionYears } from "@/lib/cockpit";
import { formatCompactNumber } from "@/lib/format";
import type { AnnualSeries } from "@/lib/types";

/** One view, not three.
 *
 * The chart used to carry Trafik / Gelir / Birim Ekonomi tabs -- nine series
 * behind a control the reader had to operate. In Kokpit V2 the traffic figures
 * are Market Pulse's first three cells and the unit economics are three of the
 * five KPI cards, both of them above this chart and both permanently visible.
 * What is left for a chart with an axis is the one thing a strip of dots
 * cannot show: the SHAPE of the revenue recovery, and how much of it is
 * ancillary.
 */
const REVENUE_KEYS = ["passenger_revenue_ytd", "ancillary_revenue_ytd"];

/**
 * IATA's 2019-2026 industry revenue series.
 *
 * The forecast tail is drawn dashed rather than hidden or silently blended
 * into the history: 2026 is a forecast and 2025 an estimate in IATA's June
 * 2026 report, and a solid line through both would claim eight years of
 * measurement where there are six. `splitForecast` (lib/cockpit.ts) is what
 * makes the two halves meet at the last real year instead of leaving a gap.
 *
 * The dashed half deliberately gets NO `lineGlow`. In this page's visual
 * grammar a glow means "live measurement", and a glowing forecast would read
 * as one.
 */
export function AnnualTrendChart({ series }: { series: AnnualSeries[] }) {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();

  const option = useMemo(() => {
    const byKey = new Map(series.map((s) => [s.metric_key, s]));
    const chosen = REVENUE_KEYS.map((key) => byKey.get(key)).filter(
      (s): s is AnnualSeries => s !== undefined,
    );
    if (chosen.length === 0) return null;

    // The UNION of both series' years, never the first series' own. The two
    // revenue series happen to be complete today; `cask` in the same table is
    // not, and a positional axis would have plotted the second series one slot
    // left with no visible symptom. `splitForecast` aligns each series to this
    // axis by YEAR and leaves a null where a year is missing.
    const years = unionYears(chosen);
    const base = baseOption(theme, reduceMotion);

    const echartsSeries = chosen.flatMap((entry, index) => {
      const color = theme.series[index % theme.series.length];
      const { actual, projected } = splitForecast(entry.points, years);
      const shared = {
        type: "line" as const,
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
          lineStyle: { color, width: 2 },
          areaStyle: { color: areaGlow(color, theme.isDark) },
        },
        {
          ...shared,
          // Same legend entry as the solid half, so the legend stays two items
          // rather than four -- `legend.data` below lists only the real names
          // and this series inherits the toggle by sharing one.
          name: entry.label_tr,
          data: projected,
          lineStyle: { color, width: 2, type: "dashed" as const, opacity: 0.85 },
          // Hollow symbols on the projected half: the same "measured vs not"
          // distinction YearDots makes in the cells above.
          symbol: "emptyCircle",
          tooltip: { show: false },
        },
      ];
    });

    return {
      ...base,
      // right: 24 rather than 8. The last x label sits centred on the final
      // tick at the grid's right edge, and `containLabel` only reserves room
      // for the AXIS labels -- "2026" was being clipped to "202".
      grid: { left: 8, right: 24, top: 30, bottom: 8, containLabel: true },
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
      yAxis: {
        ...valueAxis(theme),
        type: "value",
        scale: true,
        name: chosen[0].unit,
        nameTextStyle: { color: theme.ink, fontSize: 10 },
      },
      series: echartsSeries,
    };
  }, [series, theme, reduceMotion]);

  if (series.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-end">
        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span aria-hidden className="inline-block h-px w-5 border-t border-dashed border-current" />
          kesikli = tahmin (2025 tahmini gerçekleşme, 2026 tahmin)
        </span>
      </div>
      {option ? (
        <ReactECharts
          option={option}
          style={{ height: 240, width: "100%" }}
          opts={{ renderer: "svg" }}
          notMerge
        />
      ) : (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Gelir serisi yüklenmedi.
        </p>
      )}
    </div>
  );
}
