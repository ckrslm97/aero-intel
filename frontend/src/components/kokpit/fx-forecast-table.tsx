"use client";

import { ExternalLink } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import type { FxForecastOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

/** Curated bank FX forecasts -- see backend/app/ingest/curated_seed.py.
 * Every row is one institution's own, individually-attributed number: never
 * averaged, never re-labelled onto a normalised horizon. */
export function FxForecastTable() {
  const [pair, setPair] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<string | null>(null);

  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<FxForecastOut[]>("/kokpit/fx-forecasts", { cache: "default", signal }),
    [],
  );
  const { data: rows, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, []);

  const pairs = useMemo(
    () => [...new Set((rows ?? []).map((r) => r.currency_pair))].sort(),
    [rows],
  );
  // Horizon labels are each institution's own wording, so this is a flat set
  // of the labels actually present -- not a normalised "1m/3m/12m" bucket,
  // which would be exactly the interpolation the module this reads from
  // (curated_seed.py) exists to avoid.
  const horizons = useMemo(
    () => [...new Set((rows ?? []).map((r) => r.horizon_label))].sort(),
    [rows],
  );
  const filtered = useMemo(
    () =>
      (rows ?? []).filter(
        (r) =>
          (!pair || r.currency_pair === pair) && (!horizon || r.horizon_label === horizon),
      ),
    [rows, pair, horizon],
  );

  if (!loaded) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }
  if (error && !rows) {
    return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;
  }
  if (!rows || rows.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        Henüz küratörlü bir banka tahmini yok.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}
      <div className="flex flex-wrap gap-1.5">
        <button type="button" onClick={() => setPair(null)} className={chip(!pair)}>
          Tümü
        </button>
        {pairs.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPair(pair === p ? null : p)}
            className={chip(pair === p)}
          >
            {p}
          </button>
        ))}
        <span aria-hidden className="mx-0.5 h-4 w-px self-center bg-border" />
        <span className="self-center text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Vade
        </span>
        {horizons.map((h) => (
          <button
            key={h}
            type="button"
            onClick={() => setHorizon(horizon === h ? null : h)}
            className={chip(horizon === h)}
          >
            {h}
          </button>
        ))}
      </div>

      <Card className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <th className="px-4 py-2.5">Kurum</th>
              <th className="px-4 py-2.5">Parite</th>
              <th className="px-4 py-2.5">Vade</th>
              <th className="px-4 py-2.5 text-right">Tahmin</th>
              <th className="px-4 py-2.5">Yayın tarihi</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.map((row) => (
              <tr key={`${row.institution}-${row.currency_pair}-${row.horizon_label}`}>
                <td className="px-4 py-2.5 font-medium">{row.institution}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{row.currency_pair}</td>
                {/* The institution's own wording, verbatim -- never normalised
                    onto a shared "3 ay" column. */}
                <td className="px-4 py-2.5 text-muted-foreground">{row.horizon_label}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                  {row.value.toFixed(4)}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {new Date(row.publication_date).toLocaleDateString("tr-TR", {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                  })}
                </td>
                <td className="px-4 py-2.5">
                  <a
                    href={row.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${row.institution} kaynağına git`}
                    className="flex items-center text-muted-foreground hover:text-primary"
                  >
                    <ExternalLink className="size-3.5" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}
