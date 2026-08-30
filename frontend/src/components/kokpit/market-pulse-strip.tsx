"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { CountUp } from "@/components/motion/count-up";
import { formatRate, formatSignedPct } from "@/lib/format";
import type { IataIndicatorOut, KokpitFxBoardOut, KpiOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const Sparkline = dynamic(() => import("@/components/charts/sparkline").then((m) => m.Sparkline), {
  ssr: false,
  loading: () => <div style={{ height: 24, width: 56 }} />,
});

/** One cell of the strip. `tone` is what decides whether the delta gets a hue:
 *
 * * `neutral` -- a currency pair moving is neither good nor bad, which is the
 *   convention fx-board.tsx already renders its deltas with.
 * * `costly` -- a rise in Brent or jet fuel IS bad (up_is_good: false).
 *
 * `series` is only ever a real stored series. The two IATA cells carry no
 * sparkline at all, because an annual industry figure has eight points a
 * decade apart and nothing that could honestly be drawn at 56 pixels.
 */
interface StripCell {
  key: string;
  label: string;
  value: string;
  countTo?: number;
  unit?: string;
  deltaPct: number | null;
  tone: "neutral" | "costly";
  series?: number[];
  caption?: string;
  href?: string;
  glowVar: string;
  /** The ~15-minute cadence, the publication, the derivation -- whatever this
   * number's provenance actually is. Shown as a title, never as a claim in
   * the cell itself. */
  title?: string;
}

function DeltaPill({ deltaPct, tone }: { deltaPct: number | null; tone: StripCell["tone"] }) {
  if (deltaPct === null) return null;
  const flat = deltaPct === 0;
  const up = deltaPct > 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
        tone === "neutral" || flat
          ? "bg-muted text-muted-foreground"
          : up
            ? "bg-critical/10 text-critical"
            : "bg-good/10 text-good",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {formatSignedPct(deltaPct)}
    </span>
  );
}

function Cell({ cell }: { cell: StripCell }) {
  const body = (
    <>
      <span className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {cell.label}
        </span>
        <DeltaPill deltaPct={cell.deltaPct} tone={cell.tone} />
      </span>
      <span className="flex items-baseline gap-1">
        {cell.countTo !== undefined ? (
          <CountUp
            value={cell.countTo}
            format={() => cell.value}
            className="text-lg font-semibold tabular-nums leading-tight dark:text-glow"
          />
        ) : (
          <span className="text-lg font-semibold tabular-nums leading-tight dark:text-glow">
            {cell.value}
          </span>
        )}
        {cell.unit && <span className="text-[10px] text-muted-foreground">{cell.unit}</span>}
      </span>
      {cell.series && cell.series.length > 1 ? (
        <span className="block h-6">
          <Sparkline data={cell.series} height={24} />
        </span>
      ) : (
        <span className="block truncate text-[10px] text-muted-foreground">{cell.caption}</span>
      )}
    </>
  );

  const className = cn(
    "edge-lit flex min-w-[10.5rem] flex-1 flex-col gap-1 rounded-lg border bg-card/60 px-3 py-2 transition-[box-shadow,background-color] duration-300",
    cell.href && "hover:bg-accent/40 hover:glow-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
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

/** The dense market band under the header: two rates, two energy prices and
 * two IATA figures, in one horizontal scroll rather than six cards.
 *
 * This replaces `MarketTicker` on Kokpit. The ticker showed three KPI pills at
 * card size; this shows twice as much in less vertical space and, crucially,
 * distinguishes what is live (FX, Brent, refreshed every ~15 minutes) from
 * what is a published annual figure (the two IATA cells, which say "2026
 * tahmini" and carry no sparkline, because there is no series to draw).
 */
export function MarketPulseStrip({
  board,
  kpis,
  iata,
}: {
  board: KokpitFxBoardOut | null;
  kpis: KpiOut[];
  iata: IataIndicatorOut[];
}) {
  const pair = (name: string) => board?.pairs.find((p) => p.currency_pair === name) ?? null;
  const kpi = (key: string) => kpis.find((k) => k.metric_key === key) ?? null;
  const indicator = (metric: string) => iata.find((row) => row.metric === metric) ?? null;

  const cells: StripCell[] = [];

  for (const [name, glowVar] of [
    ["USD/TRY", "var(--chart-2)"],
    ["EUR/USD", "var(--chart-1)"],
  ] as const) {
    const fx = pair(name);
    if (!fx) continue;
    cells.push({
      key: name,
      label: name,
      value: formatRate(fx.value),
      countTo: fx.value,
      deltaPct: fx.day_delta_pct,
      tone: "neutral",
      series: fx.sparkline,
      glowVar,
      title: `${fx.source} · ${fx.frequency_label}`,
      href: name === "USD/TRY" ? "/kpi/fx_usd_try" : undefined,
    });
  }

  const brent = kpi("oil_price");
  if (brent) {
    cells.push({
      key: "oil_price",
      label: "Brent",
      value: formatRate(brent.value),
      countTo: brent.value,
      unit: brent.unit,
      deltaPct: brent.delta_pct,
      tone: "costly",
      series: brent.trend,
      glowVar: "var(--chart-5)",
      href: "/kpi/oil_price",
      title: "Yahoo Finance (BZ=F)",
    });
  }

  const fuel = kpi("fuel_price");
  if (fuel) {
    cells.push({
      key: "fuel_price",
      label: "Jet Yakıtı ˜",
      value: formatRate(fuel.value),
      countTo: fuel.value,
      unit: fuel.unit,
      deltaPct: fuel.delta_pct,
      tone: "costly",
      series: fuel.trend,
      glowVar: "var(--chart-3)",
      href: "/kpi/fuel_price",
      // The tilde in the label is the estimate mark; this says what the
      // estimate actually is, rather than leaving "˜" to be guessed at.
      title: "Tahmini: Brent + 57$ crack varsayımı (IATA Haziran 2026)",
    });
  }

  const demand = indicator("rpk_growth");
  if (demand) {
    cells.push({
      key: "rpk_growth",
      label: "Yolcu Talebi",
      value: formatSignedPct(demand.value),
      deltaPct: null,
      tone: "neutral",
      caption: `${demand.period_label_tr} tahmini · IATA`,
      glowVar: "var(--chart-4)",
      title: demand.interpretation_tr ?? undefined,
    });
  }

  const loadFactor = indicator("load_factor");
  if (loadFactor) {
    cells.push({
      key: "load_factor",
      label: "Doluluk",
      value: formatRate(loadFactor.value),
      unit: loadFactor.unit,
      deltaPct: null,
      tone: "neutral",
      caption: `${loadFactor.period_label_tr} tahmini · IATA`,
      glowVar: "var(--chart-4)",
      title: loadFactor.interpretation_tr ?? undefined,
    });
  }

  if (cells.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
        Piyasa verisi şu anda okunamıyor.
      </p>
    );
  }

  return (
    // Scrolls rather than wraps: six cells wrapping to a second row at 1280
    // pushed the signal board below the fold, which is the one thing this
    // layout exists to prevent.
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
