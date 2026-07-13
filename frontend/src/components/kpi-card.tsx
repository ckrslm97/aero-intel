import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Sparkline } from "@/components/charts/sparkline";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { formatCompactNumber, formatDelta } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface KpiCardProps {
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
  label,
  value,
  unit,
  deltaPct,
  upIsGood = true,
  trend,
  isEstimate,
  comparisonLabel = "vs previous reading",
}: KpiCardProps) {
  const isFlat = (deltaPct ?? 0) === 0;
  const isPositive = (deltaPct ?? 0) >= 0;
  const isGoodDirection = isPositive === upIsGood;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {isEstimate && (
          <span
            title="Licensed data source not yet connected -- estimated value"
            className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-secondary-foreground"
          >
            est.
          </span>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-semibold tracking-tight">
            {formatCompactNumber(value)}
          </span>
          {unit && (
            <span className="text-sm text-muted-foreground">{unit}</span>
          )}
        </div>

        {deltaPct !== undefined && (
          <div className="flex items-center gap-1 text-xs">
            {isFlat ? (
              <Minus className="size-3.5 text-muted-foreground" />
            ) : isPositive ? (
              <ArrowUpRight
                className={cn(
                  "size-3.5",
                  isGoodDirection ? "text-good" : "text-critical",
                )}
              />
            ) : (
              <ArrowDownRight
                className={cn(
                  "size-3.5",
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
  );
}
