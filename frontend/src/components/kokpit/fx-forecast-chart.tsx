"use client";

import ReactECharts from "echarts-for-react";
import { useReducedMotion } from "framer-motion";
import { useCallback, useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { baseOption, lineGlow, useChartTheme, valueAxis, withAlpha } from "@/lib/chart-theme";
import { forecastBuckets, MEDIAN_MIN_INSTITUTIONS } from "@/lib/cockpit";
import { formatRate } from "@/lib/format";
import type { FxForecastOut, KpiDetailOut } from "@/lib/types";

/** Turkish short month names for the time axis. `toLocaleDateString("tr-TR")`
 * would work in a browser but not identically under the test runner's ICU
 * build, and an axis label is not worth an ICU dependency. */
const MONTHS_TR = [
  "Oca",
  "Şub",
  "Mar",
  "Nis",
  "May",
  "Haz",
  "Tem",
  "Ağu",
  "Eyl",
  "Eki",
  "Kas",
  "Ara",
] as const;


/** metric_key per pair, for the history fetch. Only pairs the KPI cron
 * actually records appear here -- a pair with forecasts but no live metric
 * gets its markers on their own, with no history line, rather than a fake one. */
const PAIR_METRIC_KEYS: Record<string, string> = {
  "USD/TRY": "fx_usd_try",
  "EUR/TRY": "fx_eur_try",
  "EUR/USD": "fx_eur_usd",
  "GBP/TRY": "fx_gbp_try",
  "GBP/USD": "fx_gbp_usd",
  "USD/JPY": "fx_usd_jpy",
  "EUR/GBP": "fx_eur_gbp",
  "USD/CNY": "fx_usd_cny",
};

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
};

function trDate(iso: string): string {
  return new Date(iso).toLocaleDateString("tr-TR", DATE_FORMAT);
}

/**
 * One pair's real price history, with every institution's published forecast
 * as its own marker at the date it targets.
 *
 * WHAT IS DRAWN, AND WHAT IS DELIBERATELY NOT
 * -------------------------------------------
 * * The line left of today is REAL: Yahoo's own closes, fetched through the
 *   same `/kpis/{metric}?period=1y` path the KPI detail page uses. It is not
 *   extended past its last close -- there is no dotted "projection" of our own
 *   anywhere on this chart.
 * * Each institution is ONE POINT, at the date its own horizon implies (see
 *   `forecast_target_date` in backend/app/api/v1/kokpit.py for the mapping and
 *   for why "Q4 2026" lands on a quarter midpoint). The hover names the
 *   institution, the pair, the target date, the figure, the publication date
 *   and how the date was derived.
 * * The shaded band is the MIN-MAX SPREAD of the institutions sharing one
 *   target date. A spread, not a confidence interval: the rows carry no
 *   confidence field, and shading one would invent a distribution.
 * * The median line appears ONLY where at least three distinct institutions
 *   share the same target date, and is labelled "medyan · N kurum". This is
 *   the chart's version of the rule
 *   backend/app/ingest/curated_seed.py states for the data itself -- that
 *   turning one institution's horizon into another's would be "our arithmetic
 *   presented as their forecast". Two numbers have a midpoint, not a
 *   consensus; the gate lives in `forecastBuckets` (lib/cockpit.ts) so it is
 *   asserted by a test rather than by this comment.
 *
 * With the currently curated rows nothing reaches three institutions on one
 * date, so no median renders at all. That is the correct outcome, not a bug:
 * the gate is there for when the curation grows, and until then the chart says
 * only what the data says.
 */
export function FxForecastChart({
  pair,
  rows,
}: {
  pair: string;
  /** Already filtered to this pair by the caller. */
  rows: FxForecastOut[];
}) {
  const theme = useChartTheme();
  const reduceMotion = useReducedMotion();
  const metricKey = PAIR_METRIC_KEYS[pair];

  const fetcher = useCallback(
    (signal: AbortSignal) =>
      metricKey
        ? apiFetch<KpiDetailOut>(`/kpis/${metricKey}?period=1y`, { cache: "default", signal })
        : Promise.resolve(null),
    [metricKey],
  );
  const { data: detail, loaded } = useDataSource(fetcher, [metricKey]);

  const buckets = useMemo(() => forecastBuckets(rows), [rows]);

  const option = useMemo(() => {
    const history = (detail?.history ?? []).map(
      (point) => [point.as_of, point.value] as [string, number],
    );
    if (history.length === 0 && buckets.length === 0) return null;

    const base = baseOption(theme, reduceMotion);
    const forecastColor = theme.series[3];

    // Every institution's own point, carried with the metadata the tooltip
    // needs. `value` is [x, y]; the rest rides along for the formatter.
    const markers = buckets.flatMap((bucket) =>
      bucket.rows.map((row) => ({
        value: [row.target_date as string, row.value],
        institution: row.institution,
        horizonLabel: row.horizon_label,
        publicationDate: row.publication_date,
        basis: row.target_date_basis_tr,
      })),
    );

    // The band, drawn as a floor series plus a transparent-line "height"
    // series stacked on it -- ECharts' idiom for a range on a time axis.
    // Buckets where min === max contribute zero height, which is honest: one
    // institution on a date has no spread.
    const bandBuckets = buckets.filter((bucket) => bucket.rows.length > 1);
    const bandFloor = bandBuckets.map((bucket) => [bucket.targetDate, bucket.min]);
    const bandHeight = bandBuckets.map((bucket) => [bucket.targetDate, bucket.max - bucket.min]);

    const medianBuckets = buckets.filter((bucket) => bucket.median !== null);
    const medianPoints = medianBuckets.map((bucket) => ({
      value: [bucket.targetDate, bucket.median as number],
      institutionCount: bucket.institutionCount,
    }));

    return {
      ...base,
      grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
      legend: {
        top: 0,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
        data: [
          "Gerçekleşen kur",
          "Kurum tahminleri",
          ...(medianPoints.length > 0 ? ["Medyan"] : []),
        ],
        textStyle: { color: theme.ink, fontSize: 11 },
      },
      tooltip: {
        ...base.tooltip,
        trigger: "item",
        formatter: (params: {
          seriesName: string;
          data: unknown;
          value: [string, number];
        }) => {
          const point = params.data as {
            institution?: string;
            horizonLabel?: string;
            publicationDate?: string;
            basis?: string | null;
            institutionCount?: number;
          };
          if (point?.institution) {
            const lines = [
              `<b>${point.institution}</b>`,
              `Parite: ${pair}`,
              `Vade (kurumun kendi ifadesi): ${point.horizonLabel}`,
              `Hedef tarih: ${trDate(params.value[0])}`,
              `Tahmin: <b>${formatRate(params.value[1], 4)}</b>`,
              `Yayın tarihi: ${trDate(point.publicationDate as string)}`,
            ];
            if (point.basis) lines.push(`<span style="opacity:.7">${point.basis}</span>`);
            return lines.join("<br/>");
          }
          if (point?.institutionCount) {
            return [
              `<b>Medyan · ${point.institutionCount} kurum</b>`,
              `Hedef tarih: ${trDate(params.value[0])}`,
              `Medyan: <b>${formatRate(params.value[1], 4)}</b>`,
              `<span style="opacity:.7">Yalnızca aynı hedef tarihi paylaşan ${MEDIAN_MIN_INSTITUTIONS}+ kurum için çizilir.</span>`,
            ].join("<br/>");
          }
          return `${trDate(params.value[0])}<br/><b>${formatRate(params.value[1], 4)}</b>`;
        },
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: theme.gridline } },
        axisTick: { show: false },
        axisLabel: {
          color: theme.ink,
          fontSize: 11,
          hideOverlap: true,
          // AN EXPLICIT FORMATTER, and it is doing two jobs.
          //
          // A `type: "time"` axis with no formatter picks its own two-level
          // labelling, in ENGLISH and at ECharts' default 16px -- so this one
          // axis printed "Oct / Apr / Jul" on a page whose every other string
          // is Turkish, in the second-largest type on the screen, next to a
          // y axis of its own at 11px. Writing a formatter makes ECharts drop
          // the automatic level, which is what lets `fontSize: 11` above
          // finally apply.
          formatter: (value: number) => {
            const date = new Date(value);
            return date.getMonth() === 0
              ? String(date.getFullYear())
              : `${MONTHS_TR[date.getMonth()]} ${String(date.getFullYear()).slice(2)}`;
          },
        },
        splitLine: { show: false },
      },
      yAxis: {
        ...valueAxis(theme),
        type: "value",
        scale: true,
        axisLabel: {
          color: theme.ink,
          fontSize: 11,
          formatter: (v: number) => formatRate(v, v < 10 ? 2 : 0),
        },
      },
      series: [
        {
          name: "Gerçekleşen kur",
          type: "line",
          showSymbol: false,
          smooth: true,
          data: history,
          lineStyle: lineGlow(theme.primary, theme.isDark),
          itemStyle: { color: theme.primary },
          z: 3,
        },
        // --- the min-max band, as floor + stacked height ---
        {
          name: "band-floor",
          type: "line",
          stack: "forecast-band",
          data: bandFloor,
          lineStyle: { opacity: 0 },
          symbol: "none",
          silent: true,
          tooltip: { show: false },
          z: 1,
        },
        {
          name: "band-height",
          type: "line",
          stack: "forecast-band",
          data: bandHeight,
          lineStyle: { opacity: 0 },
          areaStyle: { color: withAlpha(forecastColor, theme.isDark ? 0.22 : 0.14) },
          symbol: "none",
          silent: true,
          tooltip: { show: false },
          z: 1,
        },
        {
          name: "Kurum tahminleri",
          type: "scatter",
          data: markers,
          symbolSize: 9,
          itemStyle: {
            color: forecastColor,
            borderColor: theme.surface,
            borderWidth: 1.5,
            ...(theme.isDark
              ? { shadowColor: withAlpha(forecastColor, 0.6), shadowBlur: 10 }
              : {}),
          },
          z: 4,
        },
        ...(medianPoints.length > 0
          ? [
              {
                name: "Medyan",
                type: "line" as const,
                data: medianPoints,
                symbol: "diamond",
                symbolSize: 10,
                lineStyle: { color: theme.signal, width: 2, type: "dashed" as const },
                itemStyle: { color: theme.signal },
                z: 5,
              },
            ]
          : []),
      ],
    };
  }, [detail, buckets, theme, reduceMotion, pair]);

  if (!loaded) return <Skeleton className="h-[240px] w-full rounded-xl" />;

  if (!option) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        {pair} için ne kur geçmişi ne de tarihlendirilebilir bir kurum tahmini var.
      </p>
    );
  }

  const withoutDate = rows.filter((row) => !row.target_date).length;
  const medianCount = buckets.filter((bucket) => bucket.median !== null).length;

  return (
    <div className="flex flex-col gap-1.5">
      {/* The 11px is on the CONTAINER, not only in `axisLabel`.
          ECharts 6 emits no font-size attribute on this axis' label nodes, so
          the SVG text inherited the document's 16px and the time axis rendered
          as the second-largest type on the page, next to its own y axis at 11.
          Inheriting from the wrapper fixes it for whatever the renderer leaves
          unstyled, without fighting the option tree. */}
      <div className="text-[11px]">
        <ReactECharts
          option={option}
          style={{ height: 240, width: "100%" }}
          opts={{ renderer: "svg" }}
          notMerge
        />
      </div>
      {/* Trimmed from sixty words to twenty-five. What stays is the part a
          reader cannot infer and would be misled without: the band is a RANGE,
          not a confidence interval, and the median has a floor. How "Q4 2026"
          became an x coordinate is written on each point's own tooltip, where
          the reader who needs it is already looking. */}
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Çizgi: gerçekleşen kapanışlar (Yahoo). Noktalar: kurumların kendi rakamı, kendi vadesine
        konumlandırıldı. Gölgeli alan en düşük–en yüksek <b>aralıktır</b>, güven aralığı
        değildir.{" "}
        {medianCount > 0
          ? `Medyan yalnızca aynı tarihi paylaşan ${MEDIAN_MIN_INSTITUTIONS}+ kurum olan ${medianCount} noktada çizilir.`
          : `Hiçbir hedef tarihte ${MEDIAN_MIN_INSTITUTIONS} ayrı kurum bulunmadığı için medyan çizilmemiştir.`}
        {withoutDate > 0 &&
          ` ${withoutDate} tahmin, vadesi tarihe çevrilemediği için grafikte yok; tabloda duruyor.`}
      </p>
    </div>
  );
}
