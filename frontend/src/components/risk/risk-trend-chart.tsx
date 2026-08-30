"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useMemo } from "react";

import {
  baseOption,
  categoryAxis,
  lineGlow,
  useChartTheme,
  valueAxis,
} from "@/lib/chart-theme";
import { buildRiskTrendSeries } from "@/lib/risk";
import type { RiskTrendOut } from "@/lib/types";

const DAY_LABEL = new Intl.DateTimeFormat("tr-TR", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
});

/** Daily publication volume, split by family, with high-severity over the top.
 *
 * What the bars count is the whole design constraint: risk-classified ARTICLES
 * per day, not events per day. There is no event-occurrence time anywhere in
 * this pipeline, so a spike here means "the feed wrote more about risk that
 * day" -- which is a genuinely useful thing for a desk to see, and is
 * emphatically not "more disasters happened". The caption is the API's own
 * sentence (`note`), rendered rather than restated, so the chart and the
 * endpoint cannot drift apart about it.
 *
 * High severity is a LINE over the stack, not a third bar: it is a subset of
 * the two families, and stacking a subset on top of its own supersets would
 * count those articles twice. Nothing here is dashed -- there is no forecast on
 * this page, and the dashed idiom is spoken for by the Kokpit trend chart,
 * where it means exactly one thing.
 */
export function RiskTrendChart({ trend }: { trend: RiskTrendOut }) {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();

  const option = useMemo(() => {
    const series = buildRiskTrendSeries(trend.points, trend.days);
    const base = baseOption(theme, reduceMotion);

    return {
      ...base,
      grid: { left: 8, right: 8, top: 30, bottom: 8, containLabel: true },
      legend: {
        top: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        textStyle: { color: theme.ink, fontSize: 11 },
      },
      tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        ...categoryAxis(theme),
        type: "category",
        data: series.days,
        axisLabel: {
          color: theme.ink,
          fontSize: 10,
          // Auto interval: 30 labels do not fit, and hand-picking every third
          // one breaks the moment the window changes to 7 or 90 days.
          formatter: (value: string) => DAY_LABEL.format(new Date(`${value}T00:00:00Z`)),
        },
      },
      yAxis: {
        ...valueAxis(theme),
        type: "value",
        minInterval: 1, // article counts are integers; half a headline is not a tick
      },
      series: [
        {
          name: "Doğal",
          type: "bar",
          stack: "yayin",
          data: series.natural,
          itemStyle: { color: theme.series[1], borderRadius: [0, 0, 0, 0] },
        },
        {
          name: "Çatışma",
          type: "bar",
          stack: "yayin",
          data: series.conflict,
          itemStyle: { color: theme.series[3], borderRadius: [2, 2, 0, 0] },
        },
        {
          name: "Yüksek şiddet",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 4,
          data: series.high,
          lineStyle: lineGlow(theme.critical, theme.isDark, 1.8),
          itemStyle: { color: theme.critical },
          z: 3,
        },
      ],
    };
  }, [trend, theme, reduceMotion]);

  if (trend.points.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
        Bu dönemde sınıflandırılmış risk haberi yok.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <ReactECharts
        option={option}
        style={{ height: 240, width: "100%" }}
        opts={{ renderer: "canvas" }}
        notMerge
      />
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Yayın hacmi — haber akışına göre, son{" "}
        <span className="tabular-nums">{trend.days}</span> gün. {trend.note}
      </p>
    </div>
  );
}
