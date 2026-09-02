"use client";

import { useMemo, useState } from "react";

import { MicroTrend } from "@/components/charts/micro-trend";
import { FxForecastChart } from "@/components/kokpit/fx-forecast-chart-lazy";
import { Card } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { DenseTable, DenseTd, DenseTh } from "@/components/ui/dense-table";
import { formatRate, formatUtcTime } from "@/lib/format";
import type { FxForecastOut, KokpitFxBoardOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The owner's seven pairs, in the owner's order. Fixed rather than derived
 * from the API's ordering so the table does not reshuffle when a pair is
 * temporarily missing a reading, and so USD/TRY is always the first row -- it
 * is the rate every other surface in this app anchors on. */
const PRIMARY_PAIRS = [
  "USD/TRY",
  "EUR/TRY",
  "EUR/USD",
  "GBP/TRY",
  "USD/JPY",
  "USD/CNY",
] as const;

/** Live pairs the cron records that are NOT on the owner's list.
 *
 * They go below a labelled divider rather than being dropped. Retiring a live
 * series to make a requested list fit would be destroying information to
 * satisfy a layout; putting them at the top would quietly rewrite the owner's
 * priority order. A divider says both things at once. */
const EXTRA_PAIRS = ["GBP/USD", "EUR/GBP"] as const;

const PAIR_METRIC_KEYS: Record<string, string> = {
  "USD/TRY": "fx_usd_try",
  "EUR/TRY": "fx_eur_try",
  "EUR/USD": "fx_eur_usd",
  "GBP/TRY": "fx_gbp_try",
  "USD/JPY": "fx_usd_jpy",
  "USD/CNY": "fx_usd_cny",
  "GBP/USD": "fx_gbp_usd",
  "EUR/GBP": "fx_eur_gbp",
};

export interface FxRow {
  pair: string;
  /** null for the peg, which has no history page because it has no history. */
  metricKey: string | null;
  value: string;
  dayPct: number | null;
  weekPct: number | null;
  series: number[];
  asOfLabel: string | null;
  title: string;
  /** The peg's badge, verbatim from the backend. Non-null means "this row has
   * no deltas and no trend, and that is the correct rendering". */
  pegLabel: string | null;
  forecast: { label: string; title: string } | null;
  group: "primary" | "extra";
}

/** The institution forecast closest in time to now, for one pair.
 *
 * "Closest", not "soonest": with the currently curated rows the nearest target
 * dates are a few months out, and a reader glancing at the column wants the
 * next published waypoint. Rows with no `target_date` are excluded -- the
 * mapping that derives those dates (see kokpit.py) declines to invent one
 * where the institution's wording does not support it, and this column must
 * not undo that.
 */
export function nearestForecast(
  rows: FxForecastOut[],
  pair: string,
  now: number = Date.now(),
): FxRow["forecast"] {
  const dated = rows.filter((row) => row.currency_pair === pair && row.target_date);
  if (dated.length === 0) return null;

  const nearest = dated.reduce((best, row) =>
    Math.abs(new Date(row.target_date as string).getTime() - now) <
    Math.abs(new Date(best.target_date as string).getTime() - now)
      ? row
      : best,
  );
  // Others sharing that exact target date. Counted as INSTITUTIONS, not rows:
  // one bank publishing two horizons that land on one date is one opinion.
  const sameDate = dated.filter((row) => row.target_date === nearest.target_date);
  const others = new Set(sameDate.map((row) => row.institution));
  others.delete(nearest.institution);

  const digits = nearest.value < 10 ? 4 : 2;
  const extra = others.size > 0 ? ` +${others.size} kurum` : "";
  return {
    label: `${formatRate(nearest.value, digits)} · ${nearest.institution} ${nearest.horizon_label}${extra}`,
    // Every institution on that date, each with its own wording and its own
    // number. Never averaged -- see MEDIAN_MIN_INSTITUTIONS in lib/cockpit.ts.
    title: sameDate
      .map(
        (row) =>
          `${row.institution} · ${row.horizon_label}: ${formatRate(row.value, digits)} (yayın ${row.publication_date})`,
      )
      .join("\n"),
  };
}

/**
 * Build the table's rows.
 *
 * Pure and exported so ordering, precision, the peg's shape and the
 * forecast-matching rule can be asserted without mounting a chart.
 *
 * A pair the board does not carry produces NO ROW. That is what makes GBP/TRY
 * safe to ship ahead of the backend change that starts recording it: the row
 * appears the day the first reading lands, and until then the table simply
 * does not claim to be watching it.
 */
export function buildFxRows(
  board: KokpitFxBoardOut | null,
  forecasts: FxForecastOut[],
  now?: number,
): FxRow[] {
  const byPair = new Map((board?.pairs ?? []).map((pair) => [pair.currency_pair, pair]));

  const build = (name: string, group: FxRow["group"]): FxRow | null => {
    const pair = byPair.get(name);
    if (!pair) return null;
    return {
      pair: name,
      metricKey: PAIR_METRIC_KEYS[name] ?? null,
      // Four decimals for a cross where the fourth digit is the one that
      // moves, two for a TRY or JPY rate where it is not.
      value: formatRate(pair.value, pair.value < 10 ? 4 : 2),
      dayPct: pair.day_delta_pct,
      weekPct: pair.week_delta_pct,
      series: pair.sparkline ?? [],
      asOfLabel: formatUtcTime(pair.as_of),
      title: `${pair.source} · ${pair.frequency_label}`,
      pegLabel: null,
      forecast: nearestForecast(forecasts, name, now),
      group,
    };
  };

  const rows = PRIMARY_PAIRS.map((name) => build(name, "primary")).filter(
    (row): row is FxRow => row !== null,
  );

  // The peg closes the primary block. Rendered as a badge rather than as a row
  // of dashes because there is genuinely nothing to plot: the rate has not
  // moved since 1986, and the provider's ±%0,12 of noise around it would be
  // fabricated movement if we drew it.
  if (board?.peg) {
    rows.push({
      pair: board.peg.currency_pair,
      metricKey: null,
      value: formatRate(board.peg.value, 4),
      dayPct: null,
      weekPct: null,
      series: [],
      asOfLabel: null,
      title: board.peg.source,
      pegLabel: board.peg.label,
      forecast: null,
      group: "primary",
    });
  }

  return [
    ...rows,
    ...EXTRA_PAIRS.map((name) => build(name, "extra")).filter((row): row is FxRow => row !== null),
  ];
}

/** Which pairs the forecast chart can actually draw a history line for. */
const CHARTABLE = new Set(Object.values(PAIR_METRIC_KEYS));

/**
 * KUR / FX -- live spot on the left, one pair's forecast chart on the right.
 *
 * The table row and the Market Pulse cell above are deliberately NOT the same
 * claim twice: the pulse cell answers "what is the lira doing right now", and
 * this row is the drill-down that adds the week, the trend and who has
 * published a target for it. Clicking a row moves the chart, which is what
 * makes the pair of surfaces a drill-down rather than a copy.
 *
 * There is no "1M" column. The curated forecast rows carry horizons of three
 * and twelve months and nothing shorter, so a one-month column would either be
 * empty in every row or filled by interpolating between two institutions'
 * horizons -- which is precisely the arithmetic-presented-as-their-forecast
 * that `curated_seed.py` refuses to do. The column says TAHMİN and each cell
 * prints the institution's OWN horizon wording.
 */
export function FxBoardTable({
  board,
  forecasts,
}: {
  board: KokpitFxBoardOut | null;
  forecasts: FxForecastOut[];
}) {
  const rows = useMemo(() => buildFxRows(board, forecasts), [board, forecasts]);
  const [selected, setSelected] = useState<string | null>(null);

  const chartPair = useMemo(() => {
    if (selected) return selected;
    const chartable = rows.filter((row) => row.metricKey && CHARTABLE.has(row.metricKey));
    if (chartable.some((row) => row.pair === "USD/TRY")) return "USD/TRY";
    return chartable[0]?.pair ?? null;
  }, [selected, rows]);

  const chartRows = useMemo(
    () => forecasts.filter((row) => row.currency_pair === chartPair),
    [forecasts, chartPair],
  );

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
        Kur verisi şu anda okunamıyor.
      </p>
    );
  }

  const primary = rows.filter((row) => row.group === "primary");
  const extra = rows.filter((row) => row.group === "extra");

  const renderRow = (row: FxRow) => {
    const selectable = row.metricKey !== null && CHARTABLE.has(row.metricKey);
    const isSelected = selectable && row.pair === chartPair;
    return (
      <tr
        key={row.pair}
        title={row.title}
        aria-selected={selectable ? isSelected : undefined}
        onClick={selectable ? () => setSelected(row.pair) : undefined}
        className={cn(
          "border-b border-border/60 last:border-0",
          selectable && "cursor-pointer hover:bg-accent/40",
          isSelected && "border-l-2 border-l-primary bg-primary/5",
        )}
      >
        <DenseTd className="font-medium">{row.pair}</DenseTd>
        <DenseTd numeric>{row.value}</DenseTd>
        {row.pegLabel ? (
          // The badge takes the three columns the peg has nothing to put in.
          <DenseTd colSpan={3} className="hidden sm:table-cell">
            <span className="rounded-full bg-secondary px-1.5 py-px text-[10px] font-medium text-secondary-foreground">
              {row.pegLabel}
            </span>
          </DenseTd>
        ) : (
          <>
            <DenseTd>
              {/* NEUTRAL, always. A pair rising is neither good nor bad for an
                  airline, and the backend states that at the type level by not
                  giving KokpitFxPairOut an `up_is_good`. */}
              <Delta pct={row.dayPct} tone="neutral" />
            </DenseTd>
            <DenseTd className="hidden sm:table-cell">
              <Delta pct={row.weekPct} tone="neutral" />
            </DenseTd>
            <DenseTd className="hidden lg:table-cell">
              {row.series.length > 1 ? (
                <MicroTrend data={row.series} tone="neutral" title={`${row.pair} trendi`} />
              ) : (
                <span className="text-[10px] text-muted-foreground/70">yeterli geçmiş yok</span>
              )}
            </DenseTd>
          </>
        )}
        <DenseTd
          title={row.forecast?.title}
          className={cn("truncate", row.forecast ? "text-foreground" : "text-muted-foreground/70")}
        >
          {/* A row with no forecast keeps its dash rather than leaving the
              table. The row's presence says "we watch this pair"; the dash
              says "nobody has published a target". Hiding it would conceal
              both facts at once. */}
          {row.forecast?.label ?? "—"}
        </DenseTd>
      </tr>
    );
  };

  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <div className="flex flex-col gap-1.5 xl:col-span-7">
        <Card className="p-0">
          {/* Card carries overflow-hidden, so the scroll container has to be
              inside it -- the campaign-analyst-table pattern. */}
          <div className="overflow-x-auto">
            <DenseTable>
              <thead>
                <tr>
                  <DenseTh>Parite</DenseTh>
                  <DenseTh numeric>Güncel</DenseTh>
                  <DenseTh>1G</DenseTh>
                  <DenseTh className="hidden sm:table-cell">1H</DenseTh>
                  <DenseTh className="hidden lg:table-cell">Trend</DenseTh>
                  <DenseTh>Tahmin</DenseTh>
                </tr>
              </thead>
              <tbody>
                {primary.map(renderRow)}
                {extra.length > 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-3 py-1 text-center text-[9px] uppercase tracking-wider text-muted-foreground/60"
                    >
                      — ek canlı pariteler —
                    </td>
                  </tr>
                )}
                {extra.map(renderRow)}
              </tbody>
            </DenseTable>
          </div>
        </Card>
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          Kur: Yahoo Finance · ~15 dk gecikmeli. Tahmin: kurumların kendi yayınları · ortalama
          alınmaz · medyan yalnız aynı hedef tarihte 3+ kurum varsa çizilir.
        </p>
      </div>

      <div className="flex flex-col gap-1.5 xl:col-span-5">
        {chartPair && chartRows.length > 0 ? (
          <>
            <h3 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {chartPair} · gerçekleşen kur ve kurum tahminleri
            </h3>
            <FxForecastChart pair={chartPair} rows={chartRows} />
          </>
        ) : (
          <p className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            {chartPair
              ? `${chartPair} için kurum tahmini bulunamadı.`
              : "Kurum tahmini bulunamadı."}
          </p>
        )}
      </div>
    </div>
  );
}
