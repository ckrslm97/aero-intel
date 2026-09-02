"use client";

import { YearDots } from "@/components/charts/year-dots";
import { CountUp } from "@/components/motion/count-up";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Delta } from "@/components/ui/delta";
import { formatCompactNumber } from "@/lib/format";
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

/** Percent and cent metrics carry meaningful decimals; compact notation would
 * render 8,63¢ as "8,6". */
const PRECISE_UNITS = new Set(["%", "¢/RPK", "¢/ASK"]);

function formatValue(value: number, unit: string): string {
  if (PRECISE_UNITS.has(unit)) return value.toFixed(2).replace(".", ",");
  return formatCompactNumber(value);
}

/** The empty-comparison note. CASK is the live case: its 2025 point is missing
 * upstream, so there is no year-on-year to print and saying so is the only
 * honest option -- the Sektör Dengesi block one column over does carry a
 * comparison, across the years that do exist, and says which they are. */
const NO_YOY_TITLE =
  "Önceki yılın noktası veritabanında yok; mevcut yıllar arası karşılaştırma Sektör Dengesi'nde";

function StripCell({ series }: { series: AnnualSeries }) {
  const points = series.points;
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];
  if (!latest) return null;

  // Year-on-year off the series itself rather than a second backend field: the
  // two numbers the pill compares are both in the dots underneath it, so a
  // reader can check the arithmetic without leaving the cell.
  const deltaPct =
    previous && previous.value ? ((latest.value - previous.value) / previous.value) * 100 : null;

  return (
    <div className="flex h-[76px] flex-col justify-between rounded-lg border border-border bg-card/60 px-3 py-2">
      <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {series.label_tr}
      </span>
      <span className="flex items-baseline gap-1">
        <CountUp
          value={latest.value}
          format={(v) => formatValue(v, series.unit)}
          className="text-xl font-semibold leading-none tabular-nums"
        />
        <span className="truncate text-[9px] text-muted-foreground">{series.unit}</span>
      </span>
      <Delta
        pct={deltaPct}
        // The only place `up_is_good` is consulted on this page. CASK is the
        // one metric it flips: unit cost coming DOWN is good news.
        tone={series.up_is_good ? "signed" : "costly"}
        form="pill"
        emptyTitle={NO_YOY_TITLE}
      />
      <YearDots points={points} unitLabel={series.unit} />
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
export function KpiStrip({ series }: { series: AnnualSeries[] }) {
  const byKey = new Map(series.map((s) => [s.metric_key, s]));
  const cells = STRIP_KEYS.map((key) => byKey.get(key)).filter(
    (s): s is AnnualSeries => s !== undefined,
  );

  if (cells.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
        IATA serisi henüz yüklenmedi. <code className="rounded bg-muted px-1">make seed-ingest</code>
      </p>
    );
  }

  return (
    <MotionList className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {cells.map((cell) => (
        <MotionItem key={cell.metric_key} variant="scalePop">
          <StripCell series={cell} />
        </MotionItem>
      ))}
    </MotionList>
  );
}
