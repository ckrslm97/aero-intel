"use client";

import { NotebookPen } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { DataSourceError } from "@/components/data-source-error";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import type { InsightsOut } from "@/lib/types";

/** Whether the paragraph was written by a model or assembled by rules.
 *
 * Kept visible rather than smoothed over. The backend labels every digest with
 * the provider that produced it (see backend/app/services/insights_service.py),
 * and a rule-assembled paragraph reads differently -- flatter, more literal --
 * so telling a reader which one they are looking at is the difference between
 * a summary they can calibrate and one they have to take on faith.
 */
function providerLabel(provider: string): string {
  return provider === "heuristic" ? "Kural tabanlı" : "Yapay zekâ";
}

/** The daily digest paragraph over the news archive. Sits beside Market Pulse:
 * Pulse synthesises Kokpit's own curated numbers, this one synthesises the
 * archive, and they are two different claims from two different pipelines. */
export function InsightDigestCard() {
  const fetcher = useCallback(
    (signal: AbortSignal) => apiFetch<InsightsOut>("/insights", { cache: "default", signal }),
    [],
  );
  const { data, error, loaded, retry, lastUpdated } = useDataSource(fetcher, []);

  if (!loaded) return <Skeleton className="h-40 w-full rounded-xl" />;
  if (error && !data) return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;

  const digest = data?.digest ?? null;

  return (
    <Card style={{ "--glow-color": "var(--chart-4)" } as React.CSSProperties} className="h-full p-4">
      <div className="flex items-center gap-2">
        <NotebookPen className="size-4 text-chart-4" aria-hidden />
        <h3 className="text-sm font-semibold">Günün Özeti</h3>
        {digest && (
          <span className="ml-auto flex items-center gap-2 text-[10px] text-muted-foreground">
            <span className="rounded-full bg-muted px-1.5 py-px font-medium">
              {providerLabel(digest.provider)}
            </span>
            <span className="tabular-nums">
              {new Date(digest.date).toLocaleDateString("tr-TR", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
          </span>
        )}
      </div>

      {digest ? (
        <p className="mt-2 text-sm leading-relaxed text-foreground">{digest.body}</p>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          Bugün için henüz bir özet üretilmedi.
        </p>
      )}

      <Link
        href="/insights"
        className="mt-3 w-fit rounded text-[11px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        İçgörülere git →
      </Link>
    </Card>
  );
}
