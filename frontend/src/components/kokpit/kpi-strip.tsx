"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { CountUp } from "@/components/motion/count-up";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { formatCompactNumber, formatSignedPct } from "@/lib/format";
import type { AnnualSeries } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The eight cells, in reading order. A subset of what /kokpit/annual-series
 * returns: the three revenue lines are the chart's business, not the strip's,
 * and printing all eleven would be the KPI wall this page replaced. */
const STRIP_KEYS = [
  "passengers_ytd",
  "rpk",
  "ask",
  "load_factor",
  "yield_per_rpk",
  "rask",
  "cask",
  "total_aviation_revenue_ytd",
] as const;

/** Percent and cent metrics are small numbers with meaningful decimals;
 * compact notation would render 84.0% as "84" and 8.63¢ as "8,6". */
const PRECISE_UNITS = new Set(["%", "¢/RPK", "¢/ASK"]);

function formatValue(value: number, unit: string): string {
  if (PRECISE_UNITS.has(unit)) return value.toFixed(2).replace(".", ",");
  return formatCompactNumber(value);
}

function StripCell({ series }: { series: AnnualSeries }) {
  const points = series.points;
  const latest = points[points.length - 1];
  const previous = points[points.length - 2];
  if (!latest) return null;

  // Year-on-year off the series itself, not a second backend field: the two
  // numbers the pill compares are both on screen in the chart below it, so a
  // reader can check the arithmetic.
  const deltaPct =
    previous && previous.value ? ((latest.value - previous.value) / previous.value) * 100 : null;
  const flat = (deltaPct ?? 0) === 0;
  const up = (deltaPct ?? 0) > 0;
  const goodDirection = up === series.up_is_good;
  const DeltaIcon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;

  return (
    <div className="edge-lit flex flex-col gap-1 rounded-lg border bg-card/60 px-3 py-2">
      <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {series.label_tr}
      </span>
      <span className="flex items-baseline gap-1">
        <CountUp
          value={latest.value}
          format={(v) => formatValue(v, series.unit)}
          className="text-base font-semibold tabular-nums leading-tight"
        />
        <span className="truncate text-[10px] text-muted-foreground">{series.unit}</span>
      </span>
      <span className="flex items-center gap-1.5">
        {deltaPct !== null && (
          <span
            className={cn(
              "flex items-center gap-0.5 rounded-full px-1.5 py-px text-[10px] font-semibold tabular-nums",
              flat
                ? "bg-muted text-muted-foreground"
                : goodDirection
                  ? "bg-good/10 text-good"
                  : "bg-critical/10 text-critical",
            )}
          >
            <DeltaIcon className="size-2.5" aria-hidden />
            {formatSignedPct(deltaPct)}
          </span>
        )}
        <span className="truncate text-[10px] text-muted-foreground">
          {latest.year}
          {latest.kind === "forecast" ? "T" : latest.kind === "estimate" ? "G" : ""} · IATA
        </span>
      </span>
    </div>
  );
}

/** The IATA industry headline figures, as a compact horizontal strip.
 *
 * These used to be sixteen full-height KPI cards folded away behind a
 * `<details>` nobody opened. They are real, citable, and worth ~90 pixels --
 * not a screen. Every cell is one row of the same annual series the chart
 * beneath it plots, so the strip and the chart cannot show different numbers.
 *
 * The "2026T" suffix is doing real work: T = tahmin (forecast), G = tahmini
 * gerçekleşme (estimate). No cell here is a monthly figure and none of them is
 * THY's own -- the section caption says so once, above the strip.
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
    <MotionList className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      {cells.map((cell) => (
        <MotionItem key={cell.metric_key} variant="scalePop">
          <StripCell series={cell} />
        </MotionItem>
      ))}
    </MotionList>
  );
}
