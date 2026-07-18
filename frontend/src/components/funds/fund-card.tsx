import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
import { Badge } from "@/components/ui/badge";
import { VerificationBadge } from "@/components/funds/verification-badge";
import { formatFundValue, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FundOut } from "@/lib/types";

export function FundCard({ fund }: { fund: FundOut }) {
  const hasData = fund.value !== null;
  const delta = fund.delta_pct ?? 0;
  const isFlat = delta === 0;
  const isPositive = delta >= 0;
  const deltaColor = isFlat
    ? "text-muted-foreground"
    : isPositive
      ? "text-good"
      : "text-critical";

  return (
    <Link
      href={`/invest/${fund.symbol}`}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-base font-semibold tracking-tight">{fund.symbol}</span>
          <span className="line-clamp-2 text-xs text-muted-foreground">{fund.name}</span>
        </div>
        <Badge variant="secondary" className="shrink-0">
          %{Math.round(fund.target_weight * 100)}
        </Badge>
      </div>

      {hasData ? (
        <>
          <div className="flex items-end justify-between gap-2">
            <span className="text-2xl font-semibold tracking-tight">
              {formatFundValue(fund.value!, fund.currency)}
            </span>
            {fund.delta_pct !== null && (
              <span className={cn("flex items-center gap-0.5 text-sm font-medium", deltaColor)}>
                {isFlat ? (
                  <Minus className="size-4" />
                ) : isPositive ? (
                  <ArrowUpRight className="size-4" />
                ) : (
                  <ArrowDownRight className="size-4" />
                )}
                {formatPercent(fund.delta_pct, 1)}
              </span>
            )}
          </div>
          {fund.trend.length > 1 && <Sparkline data={fund.trend} positive={isPositive} />}
        </>
      ) : (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          İlk veri güncellemesi bekleniyor
        </p>
      )}

      <VerificationBadge status={fund.verification_status} asOf={fund.as_of} />
    </Link>
  );
}
