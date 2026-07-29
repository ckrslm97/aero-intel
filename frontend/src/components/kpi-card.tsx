"use client";

import { ArrowDownRight, ArrowUpRight, CircleDashed, Minus } from "lucide-react";
import Link from "next/link";

import dynamic from "next/dynamic";

// echarts is ~1.16MB and the dashboard's only use of it on first paint is a
// 36px trend line. Loading it after the cards render keeps the landing page
// off the charting library entirely.
const Sparkline = dynamic(
  () => import("@/components/charts/sparkline").then((m) => m.Sparkline),
  { ssr: false, loading: () => <div style={{ height: 36 }} /> },
);
import { CountUp } from "@/components/motion/count-up";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { formatCompactNumber, formatDelta } from "@/lib/format";
import { KPI_ICONS } from "@/lib/kpi-icons";
import { cn } from "@/lib/utils";

export interface KpiCardProps {
  /** Backend metric_key -- used to link through to /kpi/[metric_key]. */
  metricKey: string;
  label: string;
  value: number;
  unit?: string;
  /** Percent change vs the named comparison period. */
  deltaPct?: number;
  /** Whether an increase is desirable (delays: false, load factor: true, etc). */
  upIsGood?: boolean;
  trend?: number[];
  /** True when this metric is a labelled estimate pending a licensed data source. */
  isEstimate?: boolean;
  comparisonLabel?: string;
  /** Percent change vs LY (2025). Renders a second compact delta line when set. */
  lyDeltaPct?: number;
  /** Label for the LY delta line -- backend sends "2025'e göre". */
  lyComparisonLabel?: string;
}

/** Delta rows are pills rather than bare colored text, but the icon and the
 * signed number still carry the whole meaning -- color only reinforces it. */
function deltaPill(isFlat: boolean, isGoodDirection: boolean) {
  if (isFlat) return "bg-muted text-muted-foreground";
  return isGoodDirection ? "bg-good/10 text-good" : "bg-critical/10 text-critical";
}

export function KpiCard({
  metricKey,
  label,
  value,
  unit,
  deltaPct,
  upIsGood = true,
  trend,
  isEstimate,
  comparisonLabel = "önceki ölçüme göre",
  lyDeltaPct,
  lyComparisonLabel = "2025'e göre",
}: KpiCardProps) {
  const isFlat = (deltaPct ?? 0) === 0;
  const isPositive = (deltaPct ?? 0) >= 0;
  const isGoodDirection = isPositive === upIsGood;
  const lyIsFlat = (lyDeltaPct ?? 0) === 0;
  const lyIsPositive = (lyDeltaPct ?? 0) >= 0;
  const lyIsGoodDirection = lyIsPositive === upIsGood;
  const Icon = KPI_ICONS[metricKey] ?? CircleDashed;

  return (
    <Link href={`/kpi/${metricKey}`} className="block">
      <Card
        style={{ "--glow-color": "var(--primary)" } as React.CSSProperties}
        className="relative h-full transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/50 hover:bg-accent/30 hover:glow motion-reduce:transform-none"
      >
        {/* Runway edge light along the top of the card, lit on approach. */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 hairline-glow opacity-0 transition-opacity duration-300 group-hover/card:opacity-100"
        />
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary/15 to-chart-4/20 text-primary ring-1 ring-primary/15 dark:from-primary/25 dark:to-chart-4/30 dark:ring-primary/30">
              <Icon className="size-5" />
            </span>
            <p className="text-sm font-medium text-muted-foreground">{label}</p>
          </div>
          {isEstimate && (
            <span
              title="Lisanslı veri kaynağı henüz bağlanmadı -- tahmini değer"
              className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
            >
              tahmini
            </span>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex items-baseline gap-1.5">
            <CountUp
              value={value}
              format={formatCompactNumber}
              className="text-3xl font-semibold tracking-tight tabular-nums dark:text-glow"
            />
            {unit && (
              <span className="text-base text-muted-foreground">{unit}</span>
            )}
          </div>

          {deltaPct !== undefined && (
            <div className="flex items-center gap-1.5 text-sm">
              <span
                className={cn(
                  "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                  deltaPill(isFlat, isGoodDirection),
                )}
              >
                {isFlat ? (
                  <Minus className="size-3.5" />
                ) : isPositive ? (
                  <ArrowUpRight className="size-3.5" />
                ) : (
                  <ArrowDownRight className="size-3.5" />
                )}
                {formatDelta(deltaPct)}
              </span>
              <span className="text-muted-foreground">{comparisonLabel}</span>
            </div>
          )}

          {lyDeltaPct !== undefined && (
            <div className="flex items-center gap-1.5 text-xs">
              <span
                className={cn(
                  "flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
                  deltaPill(lyIsFlat, lyIsGoodDirection),
                )}
              >
                {lyIsFlat ? (
                  <Minus className="size-3" />
                ) : lyIsPositive ? (
                  <ArrowUpRight className="size-3" />
                ) : (
                  <ArrowDownRight className="size-3" />
                )}
                {formatDelta(lyDeltaPct)}
              </span>
              <span className="text-muted-foreground">{lyComparisonLabel}</span>
            </div>
          )}

          {trend && trend.length > 1 && (
            <Sparkline data={trend} positive={isGoodDirection} />
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
