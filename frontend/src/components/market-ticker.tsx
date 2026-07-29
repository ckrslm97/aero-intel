"use client";

import { CircleDashed, Minus, TrendingDown, TrendingUp } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { formatCompactNumber, formatDelta } from "@/lib/format";
import { KPI_ICONS } from "@/lib/kpi-icons";
import type { KpiOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const Sparkline = dynamic(
  () => import("@/components/charts/sparkline").then((m) => m.Sparkline),
  { ssr: false, loading: () => <div style={{ height: 26, width: 64 }} /> },
);

/** Short forms for the strip. The backend labels ("Brent petrol", "Jet yakıtı
 * fiyatı") are written for a full-size card and are too long for a pill. */
const SHORT_LABEL: Record<string, string> = {
  oil_price: "Brent",
  fx_usd_try: "USD/TRY",
  fuel_price: "Jet Yakıtı",
};

/** Market context for the dashboard: fuel, oil and FX.
 *
 * Deliberately quieter than `KpiCard` -- muted surface, small type, a 26px
 * sparkline. These numbers frame the revenue story, they aren't the story.
 */
export function MarketTicker({ items }: { items: KpiOut[] }) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2.5">
      {items.map((kpi) => {
        const Icon = KPI_ICONS[kpi.metric_key] ?? CircleDashed;
        const delta = kpi.delta_pct;
        const isFlat = (delta ?? 0) === 0;
        const isPositive = (delta ?? 0) >= 0;
        const isGoodDirection = isPositive === kpi.up_is_good;
        const DeltaIcon = isFlat ? Minus : isPositive ? TrendingUp : TrendingDown;

        return (
          <Link
            key={kpi.metric_key}
            href={`/kpi/${kpi.metric_key}`}
            className="flex min-w-[13rem] flex-1 items-center gap-3 rounded-lg border border-border/60 bg-muted/40 px-3.5 py-2.5 transition-colors hover:bg-accent/40"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-background/70 text-muted-foreground">
              <Icon className="size-3.5" />
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {SHORT_LABEL[kpi.metric_key] ?? kpi.label}
              </span>
              <span className="flex items-baseline gap-1">
                <span className="text-sm font-semibold tabular-nums">
                  {formatCompactNumber(kpi.value)}
                </span>
                {kpi.unit && (
                  <span className="text-[10px] text-muted-foreground">{kpi.unit}</span>
                )}
              </span>
            </span>
            {delta !== null && (
              <span
                className={cn(
                  "flex shrink-0 items-center gap-0.5 text-xs font-medium tabular-nums",
                  isFlat
                    ? "text-muted-foreground"
                    : isGoodDirection
                      ? "text-good"
                      : "text-critical",
                )}
              >
                <DeltaIcon className="size-3" />
                {formatDelta(delta)}
              </span>
            )}
            {kpi.trend && kpi.trend.length > 1 && (
              <span className="ml-auto hidden w-16 shrink-0 sm:block">
                <Sparkline data={kpi.trend} positive={isGoodDirection} height={26} />
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
