"use client";

import { useMemo, useState } from "react";

import { MicroTrend } from "@/components/charts/micro-trend";
import { FxForecastChart } from "@/components/kokpit/fx-forecast-chart-lazy";
import { Card } from "@/components/ui/card";
import { Delta } from "@/components/ui/delta";
import { DenseTable, DenseTd, DenseTh } from "@/components/ui/dense-table";
import { useNow } from "@/hooks/use-now";
import { freshnessOf } from "@/lib/cockpit";
import { formatMetricValue, formatRate, formatUtcTime } from "@/lib/format";
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

/* GBP/USD AND EUR/GBP ARE NOT ON THIS BOARD, and that is a layout decision,
 * not a deletion.
 *
 * They used to sit below an "— ek canlı pariteler —" divider on the argument
 * that retiring a live series destroys information. Measured on the running
 * page, the argument did not survive contact: neither pair is on the owner's
 * list of seven, GBP/USD rendered as a row of dashes end to end (no day, no
 * week, "yeterli geçmiş yok"), and the 9px divider itself measured 2,39:1 on
 * the light surface. Two rows and a divider, for information the executive
 * page was not asked to carry.
 *
 * Nothing is destroyed: the cron still records both pairs, /kpi/fx_gbp_usd and
 * /kpi/fx_eur_gbp still draw their full history, and adding a name back to
 * PRIMARY_PAIRS is a one-line change. */
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
  /** HOW LATE this row's own reading is ("45 dk", "2 gün"), or null when it is
   * inside the live window, when there is no clock to judge against yet, and
   * for the peg.
   *
   * A per-ROW figure, because freshness is a per-row fact. The board shares one
   * badge in the page header and that badge now describes the OLDEST reading
   * (`oldestAsOf`), which is the only thing a single badge can honestly say
   * about seven pairs -- but "the worst row is two hours old" still does not
   * tell a reader WHICH row. Six pairs updating on schedule while one pair's
   * cron fails is the normal shape of this outage, and without a mark on the
   * row itself the failed pair is indistinguishable from the six. */
  delayLabel: string | null;
  title: string;
  /** The peg's badge, verbatim from the backend. Non-null means "this row has
   * no deltas and no trend, and that is the correct rendering". */
  pegLabel: string | null;
  forecast: { label: string; title: string; expired: boolean } | null;
}

/** The institution forecast a reader should see next, for one pair.
 *
 * FUTURE FIRST, then closest. The old rule was "closest in absolute time",
 * which quietly admits the past: the seeded Danske USD/TRY row targets
 * 2026-11-21, and from 2026-11-22 onward it sits ten days from now while
 * JPMorgan's live 2026-12-31 target sits thirty -- so the column would have
 * printed a SPENT forecast, under the heading "Tahmin", with no way for a
 * reader to tell. `/kokpit/fx-forecasts` applies no date filter of its own, so
 * this is the only place the distinction can be made.
 *
 * When every published target for a pair is already past, the row still shows
 * the most recent one rather than going blank -- "the last thing anyone
 * published" is information -- but it is labelled `vadesi geçti` and drawn
 * muted. That label is a statement about OUR derived `target_date`, not about
 * the institution's wording, which is why it is allowed to appear next to the
 * institution's own `horizon_label`. The derived date itself is still never
 * printed (see `FxForecastOut.target_date` in lib/types.ts).
 *
 * Rows with no `target_date` are excluded -- the mapping that derives those
 * dates (see kokpit.py) declines to invent one where the institution's wording
 * does not support it, and this column must not undo that.
 */
export function nearestForecast(
  rows: FxForecastOut[],
  pair: string,
  now: number = Date.now(),
): FxRow["forecast"] {
  const dated = rows.filter((row) => row.currency_pair === pair && row.target_date);
  if (dated.length === 0) return null;

  const time = (row: FxForecastOut) => new Date(row.target_date as string).getTime();
  const upcoming = dated.filter((row) => time(row) >= now);
  const expired = upcoming.length === 0;
  const pool = expired ? dated : upcoming;

  const nearest = pool.reduce((best, row) =>
    Math.abs(time(row) - now) < Math.abs(time(best) - now) ? row : best,
  );
  // Others sharing that exact target date. Counted as INSTITUTIONS, not rows:
  // one bank publishing two horizons that land on one date is one opinion.
  const sameDate = pool.filter((row) => row.target_date === nearest.target_date);
  const others = new Set(sameDate.map((row) => row.institution));
  others.delete(nearest.institution);

  // The pair's own precision rule, from `formatMetricValue` -- the same call
  // the spot cell above makes. An institution's 1,0850 target for EUR/USD and
  // the live 1,0850 beside it must not be quoted to different decimals.
  const quote = (value: number) => formatMetricValue(value, null, PAIR_METRIC_KEYS[pair]);
  const extra = others.size > 0 ? ` +${others.size} kurum` : "";
  const stale = expired ? " · vadesi geçti" : "";
  return {
    label: `${quote(nearest.value)} · ${nearest.institution} ${nearest.horizon_label}${extra}${stale}`,
    expired,
    // Every institution on that date, each with its own wording and its own
    // number. Never averaged -- see MEDIAN_MIN_INSTITUTIONS in lib/cockpit.ts.
    title: sameDate
      .map(
        (row) =>
          `${row.institution} · ${row.horizon_label}: ${quote(row.value)} (yayın ${row.publication_date})`,
      )
      .concat(expired ? ["Bu paritede ileri tarihli yayımlanmış tahmin kalmadı."] : [])
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
  /** The reader's clock, or null before its first tick (hooks/use-now.ts).
   * Null produces no staleness marks -- an unjudged row is drawn as an unjudged
   * row, never as a fresh one. */
  now: Date | null = null,
): FxRow[] {
  const byPair = new Map((board?.pairs ?? []).map((pair) => [pair.currency_pair, pair]));

  const build = (name: string): FxRow | null => {
    const pair = byPair.get(name);
    if (!pair) return null;
    const asOfLabel = formatUtcTime(pair.as_of);
    // The header's own rule (lib/cockpit.ts), applied per row rather than once
    // for the whole board.
    const freshness = freshnessOf(pair.as_of, now);
    return {
      pair: name,
      metricKey: PAIR_METRIC_KEYS[name] ?? null,
      // Four decimals for a cross where the fourth digit is the one that
      // moves, two for a TRY or JPY rate where it is not -- and read from
      // `formatMetricValue`, not typed here, so this table, the Market Pulse
      // cell above it and /kpi/fx_eur_usd quote one rate one way.
      value: formatMetricValue(pair.value, pair.unit, PAIR_METRIC_KEYS[name]),
      dayPct: pair.day_delta_pct,
      weekPct: pair.week_delta_pct,
      series: pair.sparkline ?? [],
      asOfLabel,
      delayLabel: freshness.delayLabel,
      // The reading's OWN time, in the row's own tooltip. `asOfLabel` was
      // computed here and then never rendered anywhere -- so the table's nine
      // rows shared one collective freshness stamp in the page header, and a
      // pair whose cron run had failed looked exactly as current as one whose
      // had not.
      title: `${pair.source} · ${pair.frequency_label}${asOfLabel ? ` · ${asOfLabel} UTC` : ""}`,
      pegLabel: null,
      // The forecast column asks a DAY-scale question -- is this institution's
      // target date already behind us -- so a clock that is up to a minute old,
      // or the render's own when there is no tick yet, answers it identically.
      // The staleness mark above is a MINUTE-scale claim and refuses to guess;
      // these are different questions and get different treatment on purpose.
      forecast: nearestForecast(forecasts, name, now?.getTime() ?? Date.now()),
    };
  };

  const rows = PRIMARY_PAIRS.map((name) => build(name)).filter(
    (row): row is FxRow => row !== null,
  );

  // The peg closes the primary block. Rendered as a badge rather than as a row
  // of dashes because there is genuinely nothing to plot: the rate has not
  // moved since 1986, and the provider's ±%0,12 of noise around it would be
  // fabricated movement if we drew it.
  //
  // Four decimals stated outright rather than read from `formatMetricValue`:
  // the peg is not one of PRIMARY_PAIRS, has no metric key and no history
  // page, and 3,7500 is how the pegged rate is quoted -- not the output of the
  // sub-10 rule that happens to agree with it.
  if (board?.peg) {
    rows.push({
      pair: board.peg.currency_pair,
      metricKey: null,
      value: formatRate(board.peg.value, 4),
      dayPct: null,
      weekPct: null,
      series: [],
      asOfLabel: null,
      // A rate that has not moved since 1986 cannot be late.
      delayLabel: null,
      title: board.peg.source,
      pegLabel: board.peg.label,
      forecast: null,
    });
  }

  return rows;
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
  // Freshness is judged on the reader's clock, not the pre-render's: this table
  // sits in a page cached for `revalidate: 60`.
  const now = useNow();
  const rows = useMemo(() => buildFxRows(board, forecasts, now), [board, forecasts, now]);
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

  const renderRow = (row: FxRow) => {
    const selectable = row.metricKey !== null && CHARTABLE.has(row.metricKey);
    const isSelected = selectable && row.pair === chartPair;
    return (
      // A selectable row is a real control, reachable from the keyboard.
      //
      // It used to be a bare `<tr onClick>` with `aria-selected`, which failed
      // twice over: `<tr>` is not focusable, so the ONLY way to move the chart
      // was a mouse -- while the section caption promised every reader that
      // "clicking a row switches the chart" -- and `aria-selected` is not
      // valid on a row outside a grid/treegrid, so assistive technology was
      // told nothing either. `role="button"` + `aria-pressed` describes what
      // this actually is: a toggle that changes the panel beside it. The
      // alternative, `role="grid"`, would borrow the whole arrow-key contract
      // of a grid widget that this table does not implement.
      <tr
        key={row.pair}
        title={row.title}
        role={selectable ? "button" : undefined}
        tabIndex={selectable ? 0 : undefined}
        aria-pressed={selectable ? isSelected : undefined}
        onClick={selectable ? () => setSelected(row.pair) : undefined}
        onKeyDown={
          selectable
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelected(row.pair);
                }
              }
            : undefined
        }
        className={cn(
          "border-b border-border/60 last:border-0",
          selectable &&
            "cursor-pointer hover:bg-accent/40 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
          isSelected && "border-l-2 border-l-primary bg-primary/5",
        )}
      >
        <DenseTd className="font-medium">{row.pair}</DenseTd>
        <DenseTd numeric>
          {/* A late row is MUTED and says how late. Every row in this table used
              to be drawn identically under one collective header stamp, so a
              pair whose cron had failed two hours ago looked exactly as current
              as the six beside it -- and the header, which read the FRESHEST
              pair, actively vouched for it. */}
          <span className={cn(row.delayLabel && "text-muted-foreground")}>{row.value}</span>
          {row.delayLabel && (
            <span
              className="ml-1 whitespace-nowrap text-[10px] font-medium text-warning"
              title={`Bu paritenin son okuması ${row.asOfLabel} UTC`}
            >
              {row.delayLabel} gecikmeli
            </span>
          )}
        </DenseTd>
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
                <span className="text-[10px] text-muted-foreground">yeterli geçmiş yok</span>
              )}
            </DenseTd>
          </>
        )}
        <DenseTd
          title={row.forecast?.title}
          className={cn(
            "truncate",
            !row.forecast || row.forecast.expired ? "text-muted-foreground" : "text-foreground",
          )}
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
              <tbody>{rows.map(renderRow)}</tbody>
            </DenseTable>
          </div>
        </Card>
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          Kur: Yahoo Finance · ~15 dk gecikmeli · trend son 48 ölçüm. Tahmin: kurumların kendi
          yayınları, ortalama alınmaz.
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
