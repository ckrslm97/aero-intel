"use client";

import { useTheme } from "next-themes";
import { useMemo } from "react";

import { formatCompactNumber } from "@/lib/format";

/* ===========================================================================
 * The one place chart colors live.
 *
 * Before this file, four chart components (insights-client, kpi-detail-chart,
 * kokpit/annual-trend-chart, charts/sparkline) each carried their own
 * `isDark ? "#.." : "#.."` ternaries, none of which referenced the
 * --chart-1..5 tokens that globals.css already defines.
 *
 * !! THIS FILE IS A MIRROR OF frontend/src/app/globals.css !!
 * The values are hardcoded rather than read via getComputedStyle so a chart
 * has its colors on the very first paint, before hydration resolves the
 * theme class. If a hex in globals.css :root/.dark ever changes, change it
 * here too -- and re-run the dataviz palette validator, since these are the
 * validated categorical/status hues.
 * ======================================================================== */

export interface ChartTheme {
  isDark: boolean;
  /** Axis labels, legends, secondary chart text. */
  ink: string;
  /** Tooltip body text -- full-contrast foreground. */
  inkStrong: string;
  /** Card surface: tooltip background, stacked-bar separators, symbol borders. */
  surface: string;
  gridline: string;
  primary: string;
  /** Brand amber. The "instrument backlight" accent. */
  signal: string;
  /** The deliberately non-identity gray for "previous period" / neutral bars. */
  neutral: string;
  good: string;
  critical: string;
  /** --chart-1..5, in order. Use for series identity. */
  series: string[];
  /** Taxonomy slug -> hex, mirroring the --category-* tokens. */
  category: Record<string, string>;
}

const LIGHT: ChartTheme = {
  isDark: false,
  ink: "#52514e",
  inkStrong: "#0b0b0b",
  surface: "#fcfcfb",
  gridline: "#e1e0d9",
  primary: "#2a78d6",
  signal: "#c98500",
  neutral: "#c8c7c0",
  good: "#0ca30c",
  critical: "#d03b3b",
  series: ["#2a78d6", "#1baf7a", "#eda100", "#4a3aa7", "#eb6834"],
  category: {
    revenue_management: "#c98500",
    fleet: "#4a3aa7",
    network: "#1baf7a",
    finance: "#eb6834",
    safety: "#d03b3b",
    regulatory: "#4f6b8f",
    sustainability: "#2f8f4e",
    airport: "#8a6d3b",
    labor: "#a63d7a",
    events: "#1a8fa0",
    general: "#6b6a65",
  },
};

const DARK: ChartTheme = {
  isDark: true,
  ink: "#c3c2b7",
  inkStrong: "#ffffff",
  surface: "#1a1a19",
  gridline: "#2c2c2a",
  primary: "#3987e5",
  signal: "#eda100",
  neutral: "#4a4a47",
  good: "#0ca30c",
  critical: "#e66767",
  series: ["#3987e5", "#199e70", "#c98500", "#9085e9", "#d95926"],
  category: {
    revenue_management: "#eda100",
    fleet: "#9085e9",
    network: "#199e70",
    finance: "#d95926",
    safety: "#e66767",
    regulatory: "#7fa3cf",
    sustainability: "#4fbf72",
    airport: "#c9a165",
    labor: "#d873b0",
    events: "#4fd0e0",
    general: "#c3c2b7",
  },
};

export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  return useMemo(() => (isDark ? DARK : LIGHT), [isDark]);
}

/** #rrggbb -> rgba(). ECharts gradients need a color string, not color-mix. */
export function withAlpha(hex: string, alpha: number): string {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Shared ECharts option fragment: tooltip chrome plus the entrance
 * animation. The animation is entrance/data-change only -- ECharts replays it
 * when the series data changes and is otherwise still -- and is switched off
 * wholesale under reduced motion. */
export function baseOption(theme: ChartTheme, reduceMotion: boolean | null) {
  return {
    textStyle: { fontFamily: "inherit" },
    animation: !reduceMotion,
    animationDuration: 700,
    animationEasing: "cubicOut",
    animationDelay: (index: number) => index * 40,
    tooltip: {
      backgroundColor: theme.surface,
      borderColor: theme.gridline,
      borderWidth: 1,
      borderRadius: 10,
      padding: [8, 12],
      extraCssText: `box-shadow: 0 10px 28px -14px rgba(0,0,0,${
        theme.isDark ? 0.75 : 0.28
      });`,
      textStyle: { color: theme.inkStrong, fontSize: 12 },
    },
  };
}

/** Axis defaults -- spread into an xAxis/yAxis of `type: "category"`. */
export function categoryAxis(theme: ChartTheme) {
  return {
    axisLine: { lineStyle: { color: theme.gridline } },
    axisTick: { show: false },
    axisLabel: { color: theme.ink, fontSize: 11 },
  };
}

/** Axis defaults -- spread into an xAxis/yAxis of `type: "value"`. The
 * compact formatter is the default rather than a per-chart opt-in: an
 * unformatted value axis renders raw magnitudes ("1.200.000.000"), which no
 * axis in this app ever wants. A chart that needs a different label (a "%"
 * axis, say) still wins -- object-spread means its own `axisLabel` replaces
 * this one wholesale. */
export function valueAxis(theme: ChartTheme) {
  return {
    splitLine: { lineStyle: { color: theme.gridline } },
    axisLabel: {
      color: theme.ink,
      fontSize: 11,
      formatter: (v: number) => formatCompactNumber(v),
    },
  };
}

/** Vertical gradient fill for an area or bar: the color bleeding away
 * downward. Stronger in dark mode, where the fill is the glow. */
export function areaGlow(color: string, isDark: boolean) {
  return {
    type: "linear" as const,
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: withAlpha(color, isDark ? 0.42 : 0.2) },
      { offset: 1, color: withAlpha(color, 0) },
    ],
  };
}

/** Line style with a neon bloom -- dark mode only. In light mode the same
 * line is just a clean 2px stroke; a glow on a near-white surface reads as a
 * printing error, not as light. */
export function lineGlow(color: string, isDark: boolean, width = 2) {
  return {
    width,
    color,
    ...(isDark
      ? {
          shadowColor: withAlpha(color, 0.55),
          shadowBlur: 12,
          shadowOffsetY: 2,
        }
      : {}),
  };
}
