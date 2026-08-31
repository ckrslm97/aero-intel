"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { formatRate, formatSignedPct } from "@/lib/format";
import type { EnergyBoardOut, KokpitFxBoardOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const Sparkline = dynamic(() => import("@/components/charts/sparkline").then((m) => m.Sparkline), {
  ssr: false,
  loading: () => <div style={{ height: 18 }} />,
});

/** One cell of the strip.
 *
 * `tone` decides whether a delta gets a hue:
 *
 * * `neutral` -- a currency pair moving is neither good nor bad, which is the
 *   convention every FX surface in this app already renders deltas with.
 * * `costly` -- a rise in Brent or jet fuel IS bad for an airline.
 *
 * `series` is only ever a real stored/published series. A cell with fewer than
 * two points draws no sparkline at all rather than a flat line through one
 * observation.
 */
export interface StripCell {
  key: string;
  label: string;
  value: string;
  unit?: string;
  dayDeltaPct: number | null;
  weekDeltaPct: number | null;
  tone: "neutral" | "costly";
  series: number[];
  href?: string;
  glowVar: string;
  /** UTC HH:MM of the reading, or null where there is no timestamp. */
  asOfLabel: string | null;
  /** Provenance -- the cadence, the publication, the derivation. A `title`,
   * never a claim printed inside the cell. */
  title?: string;
  /** A static cell that cannot move (the SAR peg). Renders the badge instead
   * of deltas, because there is nothing to plot on a rate fixed since 1986. */
  staticLabel?: string;
}

/** Turkish HH:MM in UTC, or null for a missing/unparseable timestamp. */
export function utcTimeLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("tr-TR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Delta({
  deltaPct,
  tone,
  scope,
}: {
  deltaPct: number | null;
  tone: StripCell["tone"];
  scope: string;
}) {
  if (deltaPct === null) {
    return (
      <span className="text-[10px] text-muted-foreground/70" title="Yeterli geçmiş henüz yok">
        {scope} —
      </span>
    );
  }
  const flat = deltaPct === 0;
  const up = deltaPct > 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "flex items-center gap-px text-[10px] font-semibold tabular-nums",
        tone === "neutral" || flat
          ? "text-muted-foreground"
          : up
            ? "text-critical"
            : "text-good",
      )}
    >
      <span className="font-normal text-muted-foreground">{scope}</span>
      <Icon className="size-2.5" aria-hidden />
      {formatSignedPct(deltaPct)}
    </span>
  );
}

function Cell({ cell }: { cell: StripCell }) {
  const body = (
    <>
      <span className="flex items-baseline justify-between gap-1.5">
        <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {cell.label}
        </span>
        {cell.asOfLabel && (
          <span className="shrink-0 text-[9px] tabular-nums text-muted-foreground/70">
            {cell.asOfLabel}
          </span>
        )}
      </span>

      <span className="flex items-baseline gap-1">
        <span className="text-base font-semibold leading-none tabular-nums dark:text-glow">
          {cell.value}
        </span>
        {cell.unit && <span className="text-[9px] text-muted-foreground">{cell.unit}</span>}
      </span>

      {cell.staticLabel ? (
        <span className="w-fit rounded-full bg-secondary px-1.5 py-px text-[9px] font-medium text-secondary-foreground">
          {cell.staticLabel}
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <Delta deltaPct={cell.dayDeltaPct} tone={cell.tone} scope="1g" />
          <Delta deltaPct={cell.weekDeltaPct} tone={cell.tone} scope="1h" />
        </span>
      )}

      {/* The sparkline is the last row and is allowed to be absent: a pair the
          cron started recording an hour ago has one point, and a "trend" drawn
          through one point is decoration, not data. */}
      {cell.series.length > 1 ? (
        <span className="block h-[18px]">
          <Sparkline data={cell.series} height={18} />
        </span>
      ) : (
        <span className="block h-[18px] text-[9px] leading-[18px] text-muted-foreground/70">
          {cell.staticLabel ? "" : "yeterli geçmiş yok"}
        </span>
      )}
    </>
  );

  // min-w keeps nine cells legible in one horizontal scroll; the height is
  // capped by having exactly four short rows, no card padding beyond 8px, and
  // an 18px sparkline -- ~92px, which is what lets the signal board stay in
  // the fold on a 1440x900 screen.
  const className = cn(
    "edge-lit flex w-[9.5rem] shrink-0 flex-col justify-between gap-1 rounded-lg border bg-card/60 px-2.5 py-2 transition-[box-shadow,background-color] duration-300",
    cell.href &&
      "hover:bg-accent/40 hover:glow-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
  );

  return cell.href ? (
    <Link
      href={cell.href}
      title={cell.title}
      style={{ "--glow-color": cell.glowVar } as React.CSSProperties}
      className={className}
    >
      {body}
    </Link>
  ) : (
    <div
      title={cell.title}
      style={{ "--glow-color": cell.glowVar } as React.CSSProperties}
      className={className}
    >
      {body}
    </div>
  );
}

/** Display order and runway-light colour per pair. Fixed rather than derived
 * from the API's order so the strip does not reshuffle when a pair is
 * temporarily missing a reading, and so USD/TRY is always first -- it is the
 * rate every other surface in this app anchors on. */
const FX_CELLS: { pair: string; glowVar: string; metricKey: string }[] = [
  { pair: "USD/TRY", glowVar: "var(--chart-2)", metricKey: "fx_usd_try" },
  { pair: "EUR/TRY", glowVar: "var(--chart-2)", metricKey: "fx_eur_try" },
  { pair: "EUR/USD", glowVar: "var(--chart-1)", metricKey: "fx_eur_usd" },
  { pair: "GBP/USD", glowVar: "var(--chart-1)", metricKey: "fx_gbp_usd" },
  // EUR/GBP is not on the owner's list of nine, but it IS a pair the cron
  // records and the deleted FxBoard used to show. Dropping it from the page
  // would have quietly retired live data to make a list fit; it costs one
  // cell in a row that already scrolls.
  { pair: "EUR/GBP", glowVar: "var(--chart-1)", metricKey: "fx_eur_gbp" },
  { pair: "USD/JPY", glowVar: "var(--chart-4)", metricKey: "fx_usd_jpy" },
  { pair: "USD/CNY", glowVar: "var(--chart-4)", metricKey: "fx_usd_cny" },
];

/** Energy cells, in the order the strip prints them (before FX). */
const ENERGY_CELLS: { metricKey: string; label: string; glowVar: string }[] = [
  { metricKey: "oil_price", label: "Brent", glowVar: "var(--chart-5)" },
  { metricKey: "fuel_price", label: "Jet Yakıtı ˜", glowVar: "var(--chart-3)" },
];

/** Build the strip's cells from the two boards. Pure and exported so a test
 * can assert the formatting and the honest-empty behaviour without mounting
 * ECharts. */
export function buildCells(
  board: KokpitFxBoardOut | null,
  energy: EnergyBoardOut | null,
): StripCell[] {
  const cells: StripCell[] = [];

  const energyByKey = new Map((energy?.metrics ?? []).map((row) => [row.metric_key, row]));
  for (const { metricKey, label, glowVar } of ENERGY_CELLS) {
    const row = energyByKey.get(metricKey);
    if (!row || row.value === null) continue;
    cells.push({
      key: metricKey,
      label,
      // Two decimals for a barrel price; gas at ~2,9 $/MMBtu keeps the same
      // precision because the strip is one row and mixed precision in one row
      // reads as a typo.
      value: formatRate(row.value),
      unit: row.unit,
      dayDeltaPct: row.day_change_pct,
      weekDeltaPct: row.week_change_pct,
      tone: "costly",
      series: row.sparkline,
      href: row.href,
      glowVar,
      asOfLabel: utcTimeLabel(row.as_of),
      title: row.note_tr ?? row.source,
    });
  }

  const pairByName = new Map((board?.pairs ?? []).map((pair) => [pair.currency_pair, pair]));
  for (const { pair: name, glowVar, metricKey } of FX_CELLS) {
    const pair = pairByName.get(name);
    if (!pair) continue;
    cells.push({
      key: metricKey,
      label: name,
      // Four decimals for a cross where the fourth digit is the one that
      // moves (EUR/USD at 1,1642), two for a TRY or JPY rate where it is not.
      value: formatRate(pair.value, pair.value < 10 ? 4 : 2),
      dayDeltaPct: pair.day_delta_pct,
      weekDeltaPct: pair.week_delta_pct,
      tone: "neutral",
      series: pair.sparkline,
      href: `/kpi/${metricKey}`,
      glowVar,
      asOfLabel: utcTimeLabel(pair.as_of),
      title: `${pair.source} · ${pair.frequency_label}`,
    });
  }

  // The peg last: a static badge in the same row rather than a card of its
  // own, because there is genuinely nothing to plot on a rate that has not
  // moved since 1986.
  if (board?.peg) {
    cells.push({
      key: "usd_sar_peg",
      label: board.peg.currency_pair,
      value: formatRate(board.peg.value),
      dayDeltaPct: null,
      weekDeltaPct: null,
      tone: "neutral",
      series: [],
      glowVar: "var(--muted-foreground)",
      asOfLabel: null,
      staticLabel: board.peg.label,
      title: board.peg.source,
    });
  }

  return cells;
}

/**
 * The market band under the header: every live market number Kokpit carries,
 * in ONE horizontal row.
 *
 * This replaces both the old `MarketPulseStrip` (six cells, two of them
 * IATA annual figures) and the full-width "Döviz Kuru Kokpiti" `FxBoard`
 * (five 160px cards plus a peg card, ~400px of page). Those two surfaces
 * printed the same USD/TRY twice, three hundred pixels apart, and the second
 * one pushed the signal board below the fold.
 *
 * Each cell is deliberately short (~92px): label + as-of, value, day and week
 * deltas, sparkline. A cell that cannot support a delta prints "—" with a
 * "yeterli geçmiş yok" title rather than a 0% -- EUR/TRY and GBP/USD are new
 * to the 15-minute cron and will genuinely have neither a day nor a week of
 * history for a while, and that is a fact about the data, not a rendering
 * problem to paper over.
 *
 * Every card links to its own /kpi/<metric_key> detail page, all of which
 * exist (see KPI_DISPLAY in backend/app/api/v1/kpis.py); the peg links
 * nowhere because there is no history page for a constant.
 */
export function MarketStrip({
  board,
  energy,
}: {
  board: KokpitFxBoardOut | null;
  energy: EnergyBoardOut | null;
}) {
  const cells = buildCells(board, energy);

  if (cells.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
        Piyasa verisi şu anda okunamıyor.
      </p>
    );
  }

  return (
    // Scrolls rather than wraps. Nine cells wrapping to a second row is
    // exactly the "wrap explosion" this single band exists to prevent.
    <div
      aria-label="Piyasa şeridi"
      className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:thin]"
    >
      {cells.map((cell) => (
        <Cell key={cell.key} cell={cell} />
      ))}
    </div>
  );
}
