"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import { useCallback } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { CountUp } from "@/components/motion/count-up";
import { MotionItem, MotionList } from "@/components/motion/motion-list";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { formatRate, formatSignedPct } from "@/lib/format";
import type { KokpitFxBoardOut, KokpitFxPairOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const Sparkline = dynamic(
  () => import("@/components/charts/sparkline").then((m) => m.Sparkline),
  { ssr: false, loading: () => <div style={{ height: 36 }} /> },
);

// One runway-light color per pair, cycling through the chart palette so five
// cards read as five distinct instruments rather than one repeated block.
const GLOW_VARS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

function deltaPill(deltaPct: number | null) {
  if (deltaPct === null) return null;
  const isFlat = deltaPct === 0;
  const isPositive = deltaPct > 0;
  const Icon = isFlat ? Minus : isPositive ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
        // A currency pair moving is neither good nor bad on its own -- unlike
        // KpiCard's up_is_good, so this is a neutral tone, not good/critical.
        "bg-muted text-muted-foreground",
      )}
    >
      <Icon className="size-3" />
      {formatSignedPct(deltaPct)}
    </span>
  );
}

function FxPairCard({ pair, index }: { pair: KokpitFxPairOut; index: number }) {
  return (
    <Card
      style={{ "--glow-color": GLOW_VARS[index % GLOW_VARS.length] } as React.CSSProperties}
      className="relative transition-shadow duration-300 hover:glow"
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 hairline-glow opacity-0 transition-opacity duration-300 group-hover/card:opacity-100"
      />
      <CardHeader className="flex-row items-center justify-between gap-2">
        <p className="text-sm font-semibold">{pair.currency_pair}</p>
        <span className="text-[10px] text-muted-foreground">{pair.frequency_label}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <CountUp
          value={pair.value}
          format={(v) => formatRate(v, 4)}
          className="text-2xl font-semibold tracking-tight tabular-nums dark:text-glow"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {deltaPill(pair.day_delta_pct)}
          {deltaPill(pair.week_delta_pct)}
          {deltaPill(pair.month_delta_pct)}
          {pair.day_delta_pct === null &&
            pair.week_delta_pct === null &&
            pair.month_delta_pct === null && (
              <span className="text-[11px] text-muted-foreground">
                Değişim için yeterli geçmiş henüz yok
              </span>
            )}
        </div>
        {pair.sparkline.length > 1 && <Sparkline data={pair.sparkline} />}
        <a
          href={pair.source_url ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[11px] text-muted-foreground hover:text-primary hover:underline"
        >
          {pair.source} · {new Date(pair.as_of).toLocaleTimeString("tr-TR", { timeZone: "UTC" })} UTC
        </a>
      </CardContent>
    </Card>
  );
}

/** The five live pairs plus the USD/SAR peg badge -- see
 * backend/app/api/v1/kokpit.py:get_fx_board. */
export function FxBoard() {
  const fetcher = useCallback(
    (signal: AbortSignal) => apiFetch<KokpitFxBoardOut>("/kokpit/fx", { cache: "default", signal }),
    [],
  );
  const { data: board, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, []);

  if (!loaded) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-40 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (error && !board) {
    return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;
  }

  if (!board) return null;

  return (
    <div className="flex flex-col gap-3">
      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}
      <MotionList className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {board.pairs.map((pair, index) => (
        <MotionItem key={pair.currency_pair} variant="scalePop">
          <FxPairCard pair={pair} index={index} />
        </MotionItem>
      ))}
      {/* The peg -- a static badge, not a card in the same rhythm as the live
          five: no sparkline, no deltas, because there is genuinely nothing to
          plot on a rate that hasn't moved since 1986. */}
      <MotionItem variant="scalePop">
        <Card className="flex h-full flex-col justify-center gap-1 bg-muted/40 p-1">
          <CardHeader className="pb-0">
            <p className="text-sm font-semibold">{board.peg.currency_pair}</p>
          </CardHeader>
          <CardContent className="flex flex-col gap-1.5">
            <p className="text-2xl font-semibold tabular-nums text-muted-foreground">
              {formatRate(board.peg.value)}
            </p>
            <span className="w-fit rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground">
              {board.peg.label}
            </span>
            <a
              href={board.peg.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[11px] text-muted-foreground hover:text-primary hover:underline"
            >
              {board.peg.source}
            </a>
          </CardContent>
        </Card>
      </MotionItem>
      </MotionList>
      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}
