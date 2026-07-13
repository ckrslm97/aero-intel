"use client";

import ReactECharts from "echarts-for-react";
import { useTheme } from "next-themes";

interface SparklineProps {
  data: number[];
  positive?: boolean;
  height?: number;
}

/** A 12-ish point trend line: muted throughout, with the endpoint picked out in the accent color. */
export function Sparkline({ data, positive = true, height = 36 }: SparklineProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const mutedLine = isDark ? "#3a3a38" : "#d8d7d0";
  const accent = positive ? (isDark ? "#199e70" : "#1baf7a") : (isDark ? "#e66767" : "#e34948");

  const option = {
    grid: { left: 2, right: 2, top: 4, bottom: 2 },
    xAxis: { type: "category", show: false, data: data.map((_, i) => i) },
    yAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data,
        symbol: "none",
        lineStyle: { width: 2, color: mutedLine },
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
