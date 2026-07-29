"use client";

import ReactECharts from "echarts-for-react";

import { areaGlow, useChartTheme } from "@/lib/chart-theme";

interface SparklineProps {
  data: number[];
  positive?: boolean;
  height?: number;
}

/** A 12-ish point trend line: muted throughout, with the endpoint picked out in the accent color. */
export function Sparkline({ data, positive = true, height = 36 }: SparklineProps) {
  const theme = useChartTheme();

  // Reuses the app's --muted-foreground text token (globals.css) rather than
  // a bespoke gray -- the previous #3a3a38/#d8d7d0 pair sat at ~1.4:1 contrast
  // against the card surface (well under the ~3:1 floor for a graphical mark)
  // and was effectively invisible for flat series with no shape to catch the
  // eye. This pair clears 9.7:1 (dark) / 5.3:1 (light).
  const mutedLine = theme.isDark ? "#c3c2b7" : "#6b6a65";
  // The endpoint dot. `series[1]` is the same green this file used to hardcode
  // (#1baf7a / #199e70); the negative case moves onto the validated
  // --critical token instead of the bespoke #e34948 it carried in light mode.
  const accent = positive ? theme.series[1] : theme.critical;

  // Metrics that haven't moved since the last reading (e.g. published
  // estimates re-inserted unchanged) have dataMin === dataMax. Handing ECharts
  // those equal string tokens collapses the axis to zero span and the line
  // silently fails to render. Compute the range ourselves and pad it when
  // flat so a genuinely-unchanged metric still shows as a visible flat line.
  const dataMin = Math.min(...data);
  const dataMax = Math.max(...data);
  const pad = dataMin === dataMax ? Math.abs(dataMin) * 0.05 || 1 : 0;

  const option = {
    grid: { left: 2, right: 2, top: 4, bottom: 2 },
    xAxis: { type: "category", show: false, data: data.map((_, i) => i) },
    yAxis: { type: "value", show: false, min: dataMin - pad, max: dataMax + pad },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data,
        symbol: "none",
        lineStyle: { width: 2, color: mutedLine },
        // A whisper of the endpoint color under the line, so the card's status
        // reads even at 26px. Baseline-anchored so the fill has a floor.
        areaStyle: { color: areaGlow(accent, theme.isDark), origin: "start" },
        // Deliberately still: this mark sits inside a KPI card that is already
        // playing an entrance spring, and a second clock underneath it reads
        // as jitter.
        animation: false,
        markPoint: {
          symbol: "circle",
          symbolSize: 8,
          itemStyle: { color: accent },
          data: [{ coord: [data.length - 1, data[data.length - 1]] }],
          label: { show: false },
        },
      },
    ],
  };

  return (
    <ReactECharts
      option={option}
      style={{ height, width: "100%" }}
      opts={{ renderer: "svg" }}
      notMerge
    />
  );
}
