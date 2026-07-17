import { ArrowDownRight, ArrowUpRight, CircleDashed, Minus } from "lucide-react";
import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
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
}: KpiCardProps) {
  const isFlat = (deltaPct ?? 0) === 0;
  const isPositive = (deltaPct ?? 0) >= 0;
  const isGoodDirection = isPositive === upIsGood;
  const Icon = KPI_ICONS[metricKey] ?? CircleDashed;

  return (
    <Link href={`/kpi/${metricKey}`} className="block">
      <Card className="h-full transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:bg-accent/30 hover:shadow-sm">
        <CardHeader className="flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
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
            <span className="text-3xl font-semibold tracking-tight">
              {formatCompactNumber(value)}
            </span>
            {unit && (
              <span className="text-base text-muted-foreground">{unit}</span>
            )}
          </div>

          {deltaPct !== undefined && (
            <div className="flex items-center gap-1 text-sm">
              {isFlat ? (
                <Minus className="size-4 text-muted-foreground" />
              ) : isPositive ? (
                <ArrowUpRight
                  className={cn(
                    "size-4",
                    isGoodDirection ? "text-good" : "text-critical",
                  )}
                />
              ) : (
                <ArrowDownRight
                  className={cn(
                    "size-4",
                    isGoodDirection ? "text-good" : "text-critical",
                  )}
                />
              )}
              <span
                className={cn(
                  "font-medium",
                  isFlat ? "text-muted-foreground" : isGoodDirection ? "text-good" : "text-critical",
                )}
              >
                {formatDelta(deltaPct)}
              </span>
              <span className="text-muted-foreground">{comparisonLabel}</span>
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
