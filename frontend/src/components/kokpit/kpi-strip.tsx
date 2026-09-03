"use client";

import { TriangleAlert } from "lucide-react";

import { YearDots } from "@/components/charts/year-dots";
import { CountUp } from "@/components/motion/count-up";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Delta } from "@/components/ui/delta";
import { adjacentYearPair, annualScopeLabel } from "@/lib/cockpit";
import { formatMetricValue } from "@/lib/format";
import type { AnnualSeries } from "@/lib/types";

/** Five cells, down from eight.
 *
 * RPK, ASK and load factor left this strip because they are the first three
 * cells of Market Pulse one section above, and printing them twice on one
 * screen is the duplication this redesign exists to remove. What stays is the
 * five figures that appear nowhere else: the volume, the money, and the three
 * unit economics.
 */
const STRIP_KEYS = [
  "passengers_ytd",
  "total_aviation_revenue_ytd",
  "yield_per_rpk",
  "rask",
  "cask",
] as const;

/** The empty-comparison note. CASK is the live case: its 2025 point is missing
 * upstream, so there is no year-on-year to print and saying so is the only
 * honest option -- the Sektör Dengesi block one column over does carry a
 * comparison, across the years that do exist, and says which they are.
 *
 * This note used never to fire. The cell took the last two POINTS rather than
 * two adjacent YEARS, so CASK quietly printed 2024 -> 2026T (+%11,4) in the
 * same red pill shape its four neighbours were filling with a single year's
 * move, with nothing on screen to say the windows differed. `adjacentYearPair`
 * now refuses that comparison, and the pill carries its window either way. */
const NO_YOY_TITLE =
  "Önceki yılın noktası veritabanında yok; mevcut yıllar arası karşılaştırma Sektör Dengesi'nde";

function StripCell({ series }: { series: AnnualSeries }) {
  const points = series.points;
  const latest = points[points.length - 1];
  if (!latest) return null;

  // Year-on-year off the series itself rather than a second backend field: the
  // two numbers the pill compares are both in the dots underneath it, so a
  // reader can check the arithmetic without leaving the cell. And only ever
  // across CONSECUTIVE years -- see NO_YOY_TITLE.
  const pair = adjacentYearPair(points);
  const deltaPct =
    pair && pair.previous.value
      ? ((pair.latest.value - pair.previous.value) / pair.previous.value) * 100
      : null;

  return (
    // min-h rather than a fixed height, and every child `shrink-0`. The cell
    // was h-[76px] holding 104px of children, and because the label carries
    // `truncate` (overflow: hidden) its automatic minimum size resolved to
    // ZERO -- so flex loaded the entire 28px overflow onto it and the metric
    // name rendered at 0px high at every breakpoint. RASK and CASK, which
    // share the unit ¢/ASK, were literally indistinguishable on screen.
    <div className="flex h-full min-h-[104px] flex-col justify-between gap-1 rounded-lg border border-border bg-card/60 px-3 py-2">
      <span className="shrink-0 truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {series.label_tr}
      </span>
      <span className="flex shrink-0 items-baseline gap-1">
        <CountUp
          value={latest.value}
          // Percent and cent metrics carry meaningful decimals (compact
          // notation renders 8,63¢ as "8,6"), and that rule used to be a
          // private copy here, a second one in market-pulse-row.tsx and a
          // third absent from the /kpi detail page. One rule, one file.
          format={(v) => formatMetricValue(v, series.unit, series.metric_key)}
          className="text-xl font-semibold leading-none tabular-nums"
        />
        <span className="truncate text-[10px] text-muted-foreground">{series.unit}</span>
      </span>
      <Delta
        pct={deltaPct}
        // The window, printed on the pill. Without it a yearly move wears the
        // same badge shape as the "1g" / "1h" pills two sections above, and
        // the only clue to the difference is the dot labels underneath.
        scope={pair ? annualScopeLabel(pair.previous, pair.latest) : undefined}
        // The only place `up_is_good` is consulted on this page. CASK is the
        // one metric it flips: unit cost coming DOWN is good news.
        tone={series.up_is_good ? "signed" : "costly"}
        form="pill"
        emptyTitle={NO_YOY_TITLE}
        className="shrink-0"
      />
      <YearDots points={points} unitLabel={series.unit} className="shrink-0" />
    </div>
  );
}

/**
 * The five IATA industry headline figures.
 *
 * Every cell is one row of the same annual series the IATA chart further down
 * plots, so the strip and the chart cannot show different numbers. Nothing
 * here is monthly and nothing here is THY's own -- the section caption says so
 * once, above the strip, and the year labels under each cell's dots say which
 * years are measured and which are forecast.
 */
export function KpiStrip({
  series,
  /** One extra cell, rendered last. Sektör Dengesi's unit-margin cell arrives
   * this way rather than as a panel in its own column: it is one derived
   * figure in the same shape as the five beside it, and giving it a whole
   * four-column panel cost 287px of the fold to say one thing. */
  trailing,
  /** The series endpoint did not answer, as opposed to answering with nothing.
   * Two different facts that produce the same empty `series` prop, and the
   * strip has to say which -- see the two branches below. */
  unavailable = false,
}: {
  series: AnnualSeries[];
  trailing?: React.ReactNode;
  unavailable?: boolean;
}) {
  const byKey = new Map(series.map((s) => [s.metric_key, s]));
  const cells = STRIP_KEYS.map((key) => byKey.get(key)).filter(
    (s): s is AnnualSeries => s !== undefined,
  );

  if (cells.length === 0) {
    // A SOURCE THAT DID NOT ANSWER IS NOT AN UNSEEDED DATABASE. The single
    // sentence here used to cover both, and it named the operator's fix:
    // "IATA serisi henüz yüklenmedi. make seed-ingest". On the running product
    // that is a build command printed inside an executive dashboard -- it
    // tells the reader nothing they can act on, and it asserts an empty
    // database over what is far more often a five-second outage. The empty
    // branch keeps the (true, seeded-or-not) sentence without the command; the
    // unread branch says the source was not read, which is the only thing this
    // component knows in that case.
    return unavailable ? (
      <p className="flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed border-warning/40 bg-warning/5 p-4 text-sm text-warning">
        <TriangleAlert className="size-4 shrink-0" aria-hidden />
        IATA yıllık serisi okunamadı; bu satırdaki sayılar eksik. Sayfayı yenilemeyi
        deneyin.
      </p>
    ) : (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
        IATA serisi henüz yüklenmedi.
      </p>
    );
  }

  return (
    <MotionList className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {cells.map((cell) => (
        <MotionItem key={cell.metric_key} variant="scalePop">
          <StripCell series={cell} />
        </MotionItem>
      ))}
      {trailing && <MotionItem variant="scalePop">{trailing}</MotionItem>}
    </MotionList>
  );
}
